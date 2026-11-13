using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using UnityEngine;

// Unity right/up/forward -> robot X/-Y/Z: (x, -z, y), metres.
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
    }
    public string serverAddress = "127.0.0.1";
    public int serverPort = 5005;
    public Transform target;
    public bool trackOrientation = true;
    UdpClient client;
    IPEndPoint server;
    int sequence, lastSequence = -1;
    float nextSend, lastFeedback = -100;
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

    public void RequestPreview() { queuedAction = "preview"; }
    public void ConfirmPreview() {
        if (Time.unscaledTime-lastFeedback <= 0.5f && !string.IsNullOrEmpty(previewId)) queuedAction = "confirm";
        else error = "Request a fresh preview before confirming";
    }
    public void DisableOutput() { queuedAction = "disable"; previewId = ""; }
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
        server = new IPEndPoint(IPAddress.Parse(serverAddress), serverPort);
        client = new UdpClient();
        client.Connect(server);
    }
    void Update()
    {
        if (!externalInput) {
        Vector3 direction = new Vector3(
            (Input.GetKey(KeyCode.D) ? 1 : 0) - (Input.GetKey(KeyCode.A) ? 1 : 0),
            (Input.GetKey(KeyCode.E) ? 1 : 0) - (Input.GetKey(KeyCode.Q) ? 1 : 0),
            (Input.GetKey(KeyCode.W) ? 1 : 0) - (Input.GetKey(KeyCode.S) ? 1 : 0));
        if (!externalInput) target.position += direction * (0.05f * Time.deltaTime);
        float turn = 35f * Time.deltaTime;
        if (orientationReady && !externalInput) {
            target.Rotate(Vector3.right, ((Input.GetKey(KeyCode.I)?1:0)-(Input.GetKey(KeyCode.K)?1:0))*turn, Space.Self);
            target.Rotate(Vector3.back, ((Input.GetKey(KeyCode.J)?1:0)-(Input.GetKey(KeyCode.L)?1:0))*turn, Space.Self);
            target.Rotate(Vector3.up, ((Input.GetKey(KeyCode.U)?1:0)-(Input.GetKey(KeyCode.O)?1:0))*turn, Space.Self);
        }
        if (Input.GetKeyDown(KeyCode.T)) trackOrientation = !trackOrientation;
        if (Input.GetKeyDown(KeyCode.P)) RequestPreview();
        if (Input.GetKeyDown(KeyCode.Return)) ConfirmPreview();
        if (Input.GetKeyDown(KeyCode.Escape)) DisableOutput();
        if (Input.GetKeyDown(KeyCode.G)) gripperState = gripperState == "closed" ? "open" : "closed";
        if (Input.GetKeyDown(KeyCode.R)) {
            alignAtDemoPose = false;
            SetRobotPosition(new Vector3(0, 0.15f, 0.12f));
            if (orientationReady) target.rotation = resetRotation;
        }
        if (Input.GetKeyDown(KeyCode.H)) {
            // This tested pose keeps the arm farther from its joint limits.
            SetRobotPosition(new Vector3(0, 0.16f, 0.22f));
            alignAtDemoPose = true;
            demoPoseSequence = sequence;
        }
        }
        if (Time.unscaledTime >= nextSend)
        {
            nextSend = Time.unscaledTime + 0.05f;
            Vector3 p = robotBase == null ? target.position : robotBase.InverseTransformPoint(target.position);
            Quaternion rotation = robotBase == null ? target.rotation : Quaternion.Inverse(robotBase.rotation)*target.rotation;
            var message = new TargetMessage { seq = sequence++, position = new [] {p.x, -p.z, p.y},
                orientation_enabled = trackOrientation && orientationReady && !alignAtDemoPose,
                orientation = ToRobotRotation(rotation),
                action = queuedAction, gripper = gripperState, preview_id = previewId };
            byte[] bytes = Encoding.UTF8.GetBytes(JsonUtility.ToJson(message));
            try { client.Send(bytes, bytes.Length); error = ""; queuedAction = ""; }
            catch (SocketException ex) { error = ex.Message; }
        }
        try
        {
            for (int i = 0; i < 64 && client.Available > 0; i++)
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
        catch (Exception ex) when (ex is SocketException || ex is ArgumentException) { error = ex.Message; }
        bool connected = Time.unscaledTime - lastFeedback < 0.5f;
        target.GetComponent<Renderer>().material.color = !connected ? Color.yellow : state.reachable ? Color.green : Color.red;
    }
    void OnGUI()
    {
        GUI.Box(new Rect(10,10,760,310), "TinyARM-5 | PREVIEW / DRY RUN | PHYSICAL OUTPUT LOCKED");
        Vector3 p = robotBase == null ? target.position : robotBase.InverseTransformPoint(target.position);
        string status = Time.unscaledTime-lastFeedback > 0.5f ? "Waiting for Python feedback" :
            (state.reachable ? "IK converged" : "Target rejected; holding last valid goal") + $" | IK error {state.ik_error_m*1000:F1} mm";
        string rotation = !trackOrientation ? "Orientation OFF (T to enable)" : !orientationReady ? "Waiting for initial tool orientation" :
            !state.orientation_requested ? "Initializing orientation..." :
            $"Orientation {(state.orientation_matched ? "matched" : "limited / best effort")} | IK rotation error {state.orientation_error_deg:F1} degrees";
        GUI.Label(new Rect(25,40,730,235),
            "Click Game view. WASD: horizontal | Q/E: down/up | R: reset pose\n" +
            "Rotate tool axes: I/K = X (red), J/L = Y (green), U/O = Z (blue) | T: toggle\n" +
            "H: orientation test pose (more joint headroom); wait for the arm to settle\n" +
            $"Robot target (metres): ({p.x:F3}, {-p.z:F3}, {p.y:F3})\n{status}\n{rotation}\n" +
            $"P: preview | Enter: confirm | G: gripper ({(gripperState == "" ? "omitted" : gripperState)}) | Esc: disable output\n" +
            $"Output: {state?.output_status ?? "waiting"}\n" +
            $"Preview: {(previewId == "" ? "none" : state.preview_ttl_s.ToString("F1") + " seconds remaining")}\n{error}");
        if (GUI.Button(new Rect(25,275,150,30), "Preview packet")) RequestPreview();
        if (GUI.Button(new Rect(185,275,150,30), "Confirm dry run")) ConfirmPreview();
        if (GUI.Button(new Rect(345,275,150,30), "Disable output")) DisableOutput();
    }
    void OnDestroy() { client?.Close(); if (robotPreview != null) Destroy(robotPreview.gameObject); }
}
