using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;

// World-space status panel and poke buttons, anchored beside the robot base and
// turned to face the user. Buttons are pressed by touching them with an index
// fingertip (or a controller when hands are not tracked). CONFIRM must be held.
// Buttons are ignored while the target is grabbed, so a pinch can never press one.
public class XrHud : MonoBehaviour
{
    public DesktopTarget teleop;
    public HandTeleopController hands;
    public Transform trackingOrigin;
    public Transform head;
    public Vector3 offsetInBase = new Vector3(-0.34f, 0.24f, 0.0f);
    public float confirmHoldSeconds = 0.6f;
    public float textCharacterSize = 0.0019f;
    public int textFontSize = 64;

    class Button
    {
        public string label; public Transform root; public Material material; public TextMesh text;
        public Action action; public Func<bool> isOn; public float holdSeconds;
        public bool inside, fired; public float pressedSince, lastFire = -10f;
    }
    readonly List<Button> buttons = new List<Button>();
    TextMesh title, status;
    Font font;
    const float W = 0.36f, ButtonW = 0.082f, ButtonH = 0.04f, Gap = 0.008f;
    static readonly Color Idle = new Color(0.22f, 0.24f, 0.28f), Hover = new Color(0.35f, 0.45f, 0.6f),
                          On = new Color(0.1f, 0.55f, 0.25f), Fired = new Color(0.9f, 0.75f, 0.1f);

    static Material Unlit(Color c) { var m = new Material(Shader.Find("Unlit/Color")); m.color = c; return m; }

    TextMesh Text(string name, Transform parent, Vector3 local, TextAnchor anchor, float sizeScale, Color color)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        go.transform.localPosition = local;
        var t = go.AddComponent<TextMesh>();
        t.font = font; t.fontSize = textFontSize; t.characterSize = textCharacterSize * sizeScale;
        t.anchor = anchor; t.alignment = anchor == TextAnchor.MiddleCenter ? TextAlignment.Center : TextAlignment.Left;
        t.color = color;
        go.GetComponent<MeshRenderer>().sharedMaterial = font.material;
        return t;
    }

    void AddButton(int row, int column, string label, Action action, Func<bool> isOn = null, float hold = 0f)
    {
        var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
        Destroy(quad.GetComponent<Collider>());
        quad.name = "Button " + label;
        quad.transform.SetParent(transform, false);
        float x = -W/2 + Gap + ButtonW/2 + column*(ButtonW + Gap);
        float y = -0.075f - row*(ButtonH + Gap);
        quad.transform.localPosition = new Vector3(x, y, -0.003f);
        quad.transform.localScale = new Vector3(ButtonW, ButtonH, 1f);
        var b = new Button { label = label, root = quad.transform, material = Unlit(Idle), action = action, isOn = isOn, holdSeconds = hold, pressedSince = -1f };
        quad.GetComponent<Renderer>().sharedMaterial = b.material;
        b.text = Text("Label", transform, new Vector3(x, y, -0.005f), TextAnchor.MiddleCenter, 0.8f, Color.white);
        b.text.text = label;
        buttons.Add(b);
    }

    void Start()
    {
        if (teleop == null) teleop = FindFirstObjectByType<DesktopTarget>();
        if (head == null && Camera.main != null) head = Camera.main.transform;
        font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        var panel = GameObject.CreatePrimitive(PrimitiveType.Quad);
        Destroy(panel.GetComponent<Collider>());
        panel.name = "HUD background";
        panel.transform.SetParent(transform, false);
        panel.transform.localPosition = new Vector3(0, -0.035f, 0);
        panel.transform.localScale = new Vector3(W, 0.29f, 1);
        panel.GetComponent<Renderer>().sharedMaterial = Unlit(new Color(0.05f, 0.06f, 0.08f));
        title = Text("Title", transform, new Vector3(-W/2 + 0.01f, 0.105f, -0.002f), TextAnchor.UpperLeft, 1.0f, new Color(1f, 0.8f, 0.2f));
        status = Text("Status", transform, new Vector3(-W/2 + 0.01f, 0.085f, -0.002f), TextAnchor.UpperLeft, 0.72f, Color.white);

        AddButton(0, 0, "PREVIEW", () => teleop.RequestPreview());
        AddButton(0, 1, "HOLD\nCONFIRM", () => teleop.ConfirmPreview(), () => teleop.HasPreview, confirmHoldSeconds);
        AddButton(0, 2, "CANCEL", () => teleop.CancelPreview());
        AddButton(0, 3, "DISABLE\nOUTPUT", () => teleop.DisableOutput());
        AddButton(1, 0, "GRIP\nOPEN", () => teleop.SetGripper("open"), () => teleop.gripperState == "open");
        AddButton(1, 1, "GRIP\nCLOSE", () => teleop.SetGripper("closed"), () => teleop.gripperState == "closed");
        AddButton(1, 2, "FINE", () => { if (hands) hands.fineToggle = !hands.fineToggle; }, () => hands && hands.fineToggle);
        AddButton(1, 3, "ROTATE", () => { if (hands) hands.rotationEnabled = !hands.rotationEnabled; }, () => hands && hands.rotationEnabled);
        AddButton(2, 0, "HOME\nPOSE", () => teleop.MoveToResetPose());
        AddButton(2, 1, "DEMO\nPOSE", () => teleop.MoveToDemoPose());
        AddButton(2, 2, "RESET\nCUBE", () => teleop.ResetScene());
        AddButton(2, 3, "PLACE\nBASE", () => { if (hands) hands.basePlacement = !hands.basePlacement; }, () => hands && hands.basePlacement);
    }

    void CollectPokers(List<Vector3> pokers)
    {
        if (hands != null) {
            if (hands.TryGetIndexTip(true, out Vector3 a)) pokers.Add(a);
            if (hands.TryGetIndexTip(false, out Vector3 b)) pokers.Add(b);
        }
        if (HandTeleopController.HandsActive) return; // Never mix hand aim poses with controller pokes.
        var devices = new List<InputDevice>();
        InputDevices.GetDevicesWithCharacteristics(InputDeviceCharacteristics.Controller | InputDeviceCharacteristics.TrackedDevice, devices);
        Transform origin = trackingOrigin != null ? trackingOrigin : transform.parent;
        foreach (var d in devices)
            if (d.TryGetFeatureValue(CommonUsages.devicePosition, out Vector3 p))
                pokers.Add(origin != null ? origin.TransformPoint(p) : p);
    }

    readonly List<Vector3> pokers = new List<Vector3>();

    void Update()
    {
        if (teleop == null) return;
        Place();
        pokers.Clear();
        CollectPokers(pokers);
        bool blocked = hands != null && hands.Grabbing;
        foreach (var b in buttons) UpdateButton(b, blocked);
        title.text = teleop.State != null && teleop.State.physical_enabled ? "TinyARM-5 | PHYSICAL OUTPUT ENABLED"
                   : "TinyARM-5 | SIMULATION - NOTHING SENT TO ROBOT";
        status.text = StatusText();
    }

    void Place()
    {
        Transform b = teleop.robotBase;
        Vector3 anchor = b == null ? offsetInBase : b.TransformPoint(offsetInBase);
        transform.position = anchor;
        if (head == null) return;
        Vector3 away = anchor - head.position; away.y = 0;
        if (away.sqrMagnitude < 1e-4f) return;
        Quaternion facing = Quaternion.LookRotation(away.normalized, Vector3.up);
        // Lazy follow keeps the panel steady while the user looks around.
        if (Quaternion.Angle(transform.rotation, facing) > 25f || Time.frameCount < 5)
            transform.rotation = Quaternion.Slerp(transform.rotation, facing, Time.frameCount < 5 ? 1f : 0.1f);
    }

    void UpdateButton(Button b, bool blocked)
    {
        bool inside = false;
        if (!blocked) foreach (var p in pokers) {
            Vector3 local = b.root.InverseTransformPoint(p); // quad local units: +/-0.5 in x,y
            float depth = Vector3.Dot(p - b.root.position, b.root.forward);
            if (Mathf.Abs(local.x) <= 0.55f && Mathf.Abs(local.y) <= 0.55f && depth > -0.012f && depth < 0.03f) { inside = true; break; }
        }
        if (inside && !b.inside) { b.pressedSince = Time.unscaledTime; b.fired = false; }
        if (!inside) { b.fired = false; b.pressedSince = -1f; }
        b.inside = inside;
        if (inside && !b.fired && Time.unscaledTime - b.lastFire > 0.35f &&
            Time.unscaledTime - b.pressedSince >= b.holdSeconds) {
            b.fired = true; b.lastFire = Time.unscaledTime;
            b.action?.Invoke();
        }
        bool on = b.isOn != null && b.isOn();
        b.material.color = Time.unscaledTime - b.lastFire < 0.25f ? Fired : inside ? Hover : on ? On : Idle;
        if (b.holdSeconds > 0f)
            b.text.text = inside && !b.fired ? $"HOLD {Mathf.Clamp01((Time.unscaledTime - b.pressedSince)/b.holdSeconds)*100f:F0}%" : b.label;
    }

    string StatusText()
    {
        var s = teleop.State;
        var lines = new List<string>();
        lines.Add(teleop.Connected ? $"Python {teleop.ServerLabel}: connected" :
                  teleop.Discovering ? "Python: searching LAN (start server with --lan)" :
                  $"Python {teleop.ServerLabel}: NO FEEDBACK - robot frozen");
        if (s != null && s.status_flags != null && teleop.Connected) {
            for (int i = 0; i < s.status_flags.Length; i += 3)
                lines.Add(string.Join("  |  ", s.status_flags, i, Mathf.Min(3, s.status_flags.Length - i)));
        }
        Vector3 p = teleop.RobotTargetPosition;
        if (s != null && teleop.Connected) {
            lines.Add($"Target ({p.x:F3}, {p.y:F3}, {p.z:F3}) m   IK error {s.ik_error_m*1000f:F1} mm" +
                      (s.orientation_requested ? $"   rot {(s.orientation_matched ? "matched" : "best effort")} {s.orientation_error_deg:F0} deg" : ""));
            lines.Add(teleop.HasPreview ? $"PREVIEW READY {s.preview_ttl_s:F1} s - hold CONFIRM, or move to cancel" : $"Output: {s.output_status}");
            lines.Add($"Gripper: {(string.IsNullOrEmpty(teleop.gripperState) ? "not set" : teleop.gripperState)}   Task: " +
                      (s.task_completed ? $"COMPLETE {s.task_elapsed_s:F1} s" : s.task_running ? $"{s.task_elapsed_s:F1} s" : "ready") +
                      (s.cube_grasped ? "   cube held" : ""));
            if (!string.IsNullOrEmpty(s.recording_error)) lines.Add("RECORDING ERROR: " + s.recording_error);
            else lines.Add($"Recording {s.recording_file} ({s.recorded_events} events)");
        }
        if (hands != null) lines.Add("Hand: " + hands.Status);
        if (!string.IsNullOrEmpty(teleop.LastError)) lines.Add("! " + teleop.LastError);
        return string.Join("\n", lines);
    }
}
