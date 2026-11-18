using System;
using System.Collections.Generic;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text;
using UnityEngine;
using UnityEngine.XR;

// Unity right/up/forward -> robot X/-Y/Z: (x, -z, y), metres.
// Owns the JSON/UDP link to Python. Desktop keyboard input works when no XR
// adapter has taken over (externalInput); hands/controllers call the public API.
public class DesktopTarget : MonoBehaviour
{
    [Serializable] public class TargetMessage
    {
        public int v = 1;
        public string type = "target";
        public int seq;
        public float[] position;
        public float[] orientation;
        public bool orientation_enabled;
        public string action = "";
        public string gripper = "";
        public string preview_id = "";
    }
    [Serializable] public class StateMessage
    {
        public int v;
        public string type;
        public int seq;
        public bool reachable;
        public float ik_error_m;
        public float[] position;
        public float[] goal_orientation;
        public bool orientation_requested;
        public float orientation_error_deg;
        public bool orientation_matched;
        public bool physical_enabled;
        public string output_status;
        public string preview_id;
        public float preview_ttl_s;
        public float[] preview_joints;
        public float[] values;
        public int packet_bytes;
        public string destination;
        public float[] preview_links;
        public float[] sim_links;
        public string[] status_flags;
        public float[] cube_position;
        public float[] cup_position;
        public float cup_radius;
        public float cup_height;
        public float cube_size;
        public bool cube_grasped;
        public bool cube_in_cup;
        public float task_elapsed_s;
        public bool task_running;
        public bool task_completed;
        public string gripper_state;
        public string recording_file;
        public int recorded_events;
        public string recording_error;
        public string receiver;
        public string receiver_state;
        public string receiver_summary;
    }
    [Serializable] class DiscoveryReply { public int v; public string type; public int port; }

    [Tooltip("Python laptop IPv4, 127.0.0.1 for the Editor, or 'auto' for LAN discovery")]
    public string serverAddress = "127.0.0.1";
    public int serverPort = 5006;
    public Transform target;
    public bool trackOrientation = true;
    UdpClient client, discovery;
    IPEndPoint server;
    int sequence, lastSequence = -1;
    float nextSend, nextDiscovery, lastFeedback = -100;
    StateMessage state;
    string error = "";
    bool orientationReady;
    Quaternion resetRotation;
    bool alignAtDemoPose;
    int demoPoseSequence;
    string queuedAction = "", previewId = "";
    public string gripperState = ""; // Logical only; raw calibration belongs to Python.
    public bool externalInput;
    public bool PoseReady => orientationReady;
    public Transform robotBase;
    RobotPreview robotPreview;
    bool discovering;
    public TeleopConfig Config { get; private set; } = new TeleopConfig();
    public string ConfigSource { get; private set; } = "";

    public StateMessage State => state;
    public bool Connected => Time.unscaledTime - lastFeedback < 0.5f;
    public bool Discovering => discovering && !Connected;
    public string ServerLabel => server == null ? (discovering ? "searching LAN..." : "none") : server.ToString();
    public string LastError => error;
    public bool HasPreview => !string.IsNullOrEmpty(previewId);
    public Vector3 RobotTargetPosition {
        get { Vector3 p = robotBase == null ? target.position : robotBase.InverseTransformPoint(target.position);
              return new Vector3(p.x, -p.z, p.y); }
    }

    public void RequestPreview() { queuedAction = "preview"; }
    public void ConfirmPreview() {
        if (Connected && !string.IsNullOrEmpty(previewId)) queuedAction = "confirm";
        else error = "Request a fresh preview before confirming";
    }
    public void DisableOutput() { queuedAction = "disable"; previewId = ""; }
    // Clears a pending preview without disabling output (tracking loss, grab start).
    public void CancelPreview() { if (!string.IsNullOrEmpty(previewId) && queuedAction == "") queuedAction = "cancel"; previewId = ""; }
    public void ResetScene() { queuedAction = "reset_scene"; }
    public void SetGripper(string logical) { if (logical == "open" || logical == "closed") gripperState = logical; }
    public void MoveToResetPose() {
        alignAtDemoPose = false;
        SetRobotPosition(new Vector3(0, 0.15f, 0.12f));
        if (orientationReady) target.rotation = resetRotation;
    }
    public void MoveToDemoPose() {
        // This tested pose keeps the arm farther from its joint limits.
        SetRobotPosition(new Vector3(0, 0.16f, 0.22f));
        alignAtDemoPose = true;
        demoPoseSequence = sequence;
    }
    void SetRobotPosition(Vector3 position) {
        target.position = robotBase == null ? position : robotBase.TransformPoint(position);
    }

    // Change of basis R_robot = C * R_unity * inverse(C), C(x,y,z)=(x,-z,y).
    public static float[] ToRobotRotation(Quaternion q) => new [] {q.w, q.x, -q.z, q.y};
    public static Quaternion ToUnityRotation(float[] q) => new Quaternion(q[1], q[3], -q[2], q[0]).normalized;

    void Start()
    {
        Application.runInBackground = true;
        TargetAxes.Ensure(target);
        robotPreview = new GameObject("Amber IK goal preview (not physical feedback)").AddComponent<RobotPreview>();
        robotPreview.robotBase = robotBase;
        Config = TeleopConfig.Load(out string source);
        ConfigSource = source;
        if (!string.IsNullOrWhiteSpace(Config.serverAddress)) serverAddress = Config.serverAddress.Trim();
        if (Config.serverPort > 0) serverPort = Config.serverPort;
        if (string.Equals(serverAddress, "auto", StringComparison.OrdinalIgnoreCase)) {
            discovering = true;
            // Try the last server that answered while discovery runs in parallel.
            string last = PlayerPrefs.GetString("tinyarm.lastServer", "");
            if (IPAddress.TryParse(last, out IPAddress lastAddress)) Connect(new IPEndPoint(lastAddress, serverPort));
        } else if (IPAddress.TryParse(serverAddress, out IPAddress address)) {
            Connect(new IPEndPoint(address, serverPort));
        } else {
            error = $"Invalid server address '{serverAddress}'";
        }
    }

    void Connect(IPEndPoint endpoint)
    {
        client?.Close();
        server = endpoint;
        client = new UdpClient();
        client.Connect(server);
        lastSequence = -1;
    }

    static List<IPAddress> BroadcastAddresses()
    {
        var result = new List<IPAddress> { IPAddress.Broadcast };
        try {
            foreach (var nic in NetworkInterface.GetAllNetworkInterfaces()) {
                if (nic.OperationalStatus != OperationalStatus.Up) continue;
                foreach (var unicast in nic.GetIPProperties().UnicastAddresses) {
                    if (unicast.Address.AddressFamily != AddressFamily.InterNetwork || IPAddress.IsLoopback(unicast.Address)) continue;
                    byte[] ip = unicast.Address.GetAddressBytes();
                    byte[] mask = unicast.IPv4Mask != null ? unicast.IPv4Mask.GetAddressBytes() : new byte[] {255,255,255,0};
                    if (mask.Length != 4 || (mask[0] | mask[1] | mask[2] | mask[3]) == 0) mask = new byte[] {255,255,255,0};
                    var b = new byte[4];
                    for (int i = 0; i < 4; i++) b[i] = (byte)(ip[i] | ~mask[i]);
                    var broadcast = new IPAddress(b);
                    if (!result.Contains(broadcast)) result.Add(broadcast);
                }
            }
        } catch (Exception) { /* Some Android builds restrict interface enumeration. */ }
        return result;
    }

    void Discover()
    {
        if (!discovering || Connected) return;
        try {
            if (discovery == null) { discovery = new UdpClient(0); discovery.EnableBroadcast = true; }
            if (Time.unscaledTime >= nextDiscovery) {
                nextDiscovery = Time.unscaledTime + 1f;
                byte[] request = Encoding.UTF8.GetBytes("{\"v\":1,\"type\":\"discover\"}");
                foreach (var address in BroadcastAddresses())
                    discovery.Send(request, request.Length, new IPEndPoint(address, serverPort));
            }
            for (int i = 0; i < 8 && discovery.Available > 0; i++) {
                IPEndPoint source = null;
                var reply = JsonUtility.FromJson<DiscoveryReply>(Encoding.UTF8.GetString(discovery.Receive(ref source)));
                if (reply != null && reply.v == 1 && reply.type == "discover_reply") {
                    Connect(new IPEndPoint(source.Address, reply.port > 0 ? reply.port : serverPort));
                    PlayerPrefs.SetString("tinyarm.lastServer", source.Address.ToString());
                    PlayerPrefs.Save();
                    error = "";
                }
            }
        } catch (Exception ex) when (ex is SocketException || ex is ArgumentException || ex is ObjectDisposedException) {
            error = "Discovery: " + ex.Message;
        }
    }

    void Update()
    {
        if (!externalInput) {
        Vector3 direction = new Vector3(
            (Input.GetKey(KeyCode.D) ? 1 : 0) - (Input.GetKey(KeyCode.A) ? 1 : 0),
            (Input.GetKey(KeyCode.E) ? 1 : 0) - (Input.GetKey(KeyCode.Q) ? 1 : 0),
            (Input.GetKey(KeyCode.W) ? 1 : 0) - (Input.GetKey(KeyCode.S) ? 1 : 0));
        target.position += direction * (0.05f * Time.deltaTime);
        float turn = 35f * Time.deltaTime;
        if (orientationReady) {
            target.Rotate(Vector3.right, ((Input.GetKey(KeyCode.I)?1:0)-(Input.GetKey(KeyCode.K)?1:0))*turn, Space.Self);
            target.Rotate(Vector3.back, ((Input.GetKey(KeyCode.J)?1:0)-(Input.GetKey(KeyCode.L)?1:0))*turn, Space.Self);
            target.Rotate(Vector3.up, ((Input.GetKey(KeyCode.U)?1:0)-(Input.GetKey(KeyCode.O)?1:0))*turn, Space.Self);
        }
        if (Input.GetKeyDown(KeyCode.T)) trackOrientation = !trackOrientation;
        if (Input.GetKeyDown(KeyCode.P)) RequestPreview();
        if (Input.GetKeyDown(KeyCode.Return)) ConfirmPreview();
        if (Input.GetKeyDown(KeyCode.Escape)) DisableOutput();
        if (Input.GetKeyDown(KeyCode.G)) gripperState = gripperState == "closed" ? "open" : "closed";
        if (Input.GetKeyDown(KeyCode.R)) MoveToResetPose();
        if (Input.GetKeyDown(KeyCode.H)) MoveToDemoPose();
        if (Input.GetKeyDown(KeyCode.C)) CancelPreview();
        if (Input.GetKeyDown(KeyCode.N)) ResetScene();
        }
        Discover();
        if (client != null && Time.unscaledTime >= nextSend)
        {
            nextSend = Time.unscaledTime + 0.05f;
            Vector3 p = robotBase == null ? target.position : robotBase.InverseTransformPoint(target.position);
            Quaternion rotation = robotBase == null ? target.rotation : Quaternion.Inverse(robotBase.rotation)*target.rotation;
            var message = new TargetMessage { seq = sequence++, position = new [] {p.x, -p.z, p.y},
                orientation_enabled = trackOrientation && orientationReady && !alignAtDemoPose,
                orientation = ToRobotRotation(rotation),
                action = queuedAction, gripper = gripperState, preview_id = previewId };
            byte[] bytes = Encoding.UTF8.GetBytes(JsonUtility.ToJson(message));
            try { client.Send(bytes, bytes.Length); if (!error.StartsWith("Request")) error = ""; queuedAction = ""; }
            catch (Exception ex) when (ex is SocketException || ex is ObjectDisposedException) { error = ex.Message; }
        }
        try
        {
            for (int i = 0; client != null && i < 64 && client.Available > 0; i++)
            {
                IPEndPoint source = null;
                var update = JsonUtility.FromJson<StateMessage>(Encoding.UTF8.GetString(client.Receive(ref source)));
                if (update.v == 1 && update.type == "state" && update.seq > lastSequence)
                {
                    state = update; lastSequence = update.seq; lastFeedback = Time.unscaledTime;
                    previewId = update.preview_id ?? "";
                    robotPreview.UpdatePreview(update.preview_links);
                    // Start with a reachable tool orientation rather than an arbitrary identity.
                    if (!orientationReady && update.reachable && update.goal_orientation != null && update.goal_orientation.Length == 4) {
                        resetRotation = ToUnityRotation(update.goal_orientation);
                        if (robotBase != null) resetRotation = robotBase.rotation * resetRotation;
                        target.rotation = resetRotation;
                        orientationReady = true;
                    }
                    if (alignAtDemoPose && update.seq >= demoPoseSequence && update.reachable &&
                        !update.orientation_requested && update.goal_orientation != null && update.goal_orientation.Length == 4) {
                        target.rotation = ToUnityRotation(update.goal_orientation);
                        if (robotBase != null) target.rotation = robotBase.rotation * target.rotation;
                        alignAtDemoPose = false;
                    }
                }
            }
        }
        // A Windows/Android ICMP "port unreachable" surfaces as SocketException on Receive.
        catch (Exception ex) when (ex is SocketException || ex is ArgumentException || ex is ObjectDisposedException) { error = ex.Message; }
        var renderer = target.GetComponent<Renderer>();
        if (renderer != null)
            renderer.material.color = !Connected || state == null ? Color.yellow : state.reachable ? Color.green : Color.red;
    }
    void OnGUI()
    {
        if (XRSettings.isDeviceActive) return; // The headset uses the world-space HUD instead.
        GUI.Box(new Rect(10,10,760,330), "TinyARM-5 | SIMULATION + RECORDING | PHYSICAL OUTPUT LOCKED");
        Vector3 p = robotBase == null ? target.position : robotBase.InverseTransformPoint(target.position);
        string status = !Connected || state == null ? $"Waiting for Python feedback ({ServerLabel})" :
            (state.reachable ? "IK converged" : "Target rejected; holding last valid goal") + $" | IK error {state.ik_error_m*1000:F1} mm";
        string rotation = !trackOrientation ? "Orientation OFF (T to enable)" : !orientationReady ? "Waiting for initial tool orientation" :
            state == null || !state.orientation_requested ? "Initializing orientation..." :
            $"Orientation {(state.orientation_matched ? "matched" : "limited / best effort")} | IK rotation error {state.orientation_error_deg:F1} degrees";
        string flags = state?.status_flags == null ? "" : string.Join(" | ", state.status_flags);
        GUI.Label(new Rect(25,40,730,255),
            "Click Game view. WASD: horizontal | Q/E: down/up | R: reset pose | N: reset cube/timer\n" +
            "Rotate tool axes: I/K = X (red), J/L = Y (green), U/O = Z (blue) | T: toggle\n" +
            "H: orientation test pose (more joint headroom); wait for the arm to settle\n" +
            $"Robot target (metres): ({p.x:F3}, {-p.z:F3}, {p.y:F3})\n{status}\n{rotation}\n" +
            $"P: preview | Enter: confirm | C: cancel | G: gripper ({(gripperState == "" ? "omitted" : gripperState)}) | Esc: disable output\n" +
            $"Output: {state?.output_status ?? "waiting"}\n" +
            $"Preview: {(previewId == "" || state == null ? "none" : state.preview_ttl_s.ToString("F1") + " seconds remaining")}\n{flags}\n{error}");
        if (GUI.Button(new Rect(25,300,150,30), "Preview")) RequestPreview();
        if (GUI.Button(new Rect(185,300,150,30), "Confirm")) ConfirmPreview();
        if (GUI.Button(new Rect(345,300,150,30), "Disable output")) DisableOutput();
    }
    void OnDestroy() { client?.Close(); discovery?.Close(); if (robotPreview != null) Destroy(robotPreview.gameObject); }
}
