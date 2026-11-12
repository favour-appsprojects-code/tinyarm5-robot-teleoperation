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
    }
    [Serializable] public class StateMessage
    {
        public int v;
        public string type;
        public int seq;
        public bool reachable;
        public float ik_error_m;
        public float[] position;
    }
    public string serverAddress = "127.0.0.1";
    public int serverPort = 5005;
    public Transform target;
    UdpClient client;
    IPEndPoint server;
    int sequence, lastSequence = -1;
    float nextSend, lastFeedback = -100;
    StateMessage state;
    string error = "";

    void Start()
    {
        Application.runInBackground = true;
        server = new IPEndPoint(IPAddress.Parse(serverAddress), serverPort);
        client = new UdpClient();
        client.Connect(server);
    }
    void Update()
    {
        Vector3 direction = new Vector3(
            (Input.GetKey(KeyCode.D) ? 1 : 0) - (Input.GetKey(KeyCode.A) ? 1 : 0),
            (Input.GetKey(KeyCode.E) ? 1 : 0) - (Input.GetKey(KeyCode.Q) ? 1 : 0),
            (Input.GetKey(KeyCode.W) ? 1 : 0) - (Input.GetKey(KeyCode.S) ? 1 : 0));
        target.position += direction * (0.05f * Time.deltaTime);
        if (Input.GetKeyDown(KeyCode.R)) target.position = new Vector3(0, 0.15f, 0.12f);
        if (Time.unscaledTime >= nextSend)
        {
            nextSend = Time.unscaledTime + 0.05f;
            Vector3 p = target.position;
            var message = new TargetMessage { seq = sequence++, position = new [] {p.x, -p.z, p.y} };
            byte[] bytes = Encoding.UTF8.GetBytes(JsonUtility.ToJson(message));
            try { client.Send(bytes, bytes.Length); error = ""; }
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
                }
            }
        }
        catch (Exception ex) when (ex is SocketException || ex is ArgumentException) { error = ex.Message; }
        bool connected = Time.unscaledTime - lastFeedback < 0.5f;
        target.GetComponent<Renderer>().material.color = !connected ? Color.yellow : state.reachable ? Color.green : Color.red;
    }
    void OnGUI()
    {
        GUI.Box(new Rect(10,10,620,150), "TinyARM-5 | SIMULATION ONLY");
        Vector3 p = target.position;
        string status = Time.unscaledTime-lastFeedback > 0.5f ? "Waiting for Python feedback" :
            (state.reachable ? "IK converged" : "Target rejected; holding last valid goal") + $" | IK error {state.ik_error_m*1000:F1} mm";
        GUI.Label(new Rect(25,40,590,110),
            "Click Game view. WASD: horizontal | Q/E: down/up | R: reset\n" +
            $"Robot target (metres): ({p.x:F3}, {-p.z:F3}, {p.y:F3})\n{status}\n{error}");
    }
    void OnDestroy() { client?.Close(); }
}
