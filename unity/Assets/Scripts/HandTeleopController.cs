using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.Hands;

// Primary Quest interaction: pinch-clutched, filtered, scaled hand control of
// the IK target, expressed in the calibrated robot-base frame.
//
// - Dominant-hand pinch (thumb-index, with hysteresis + debounce) grabs the
//   target from wherever the hand is: relative "clutch" motion, so there is no
//   jump on grab and the hand never has to occlude the target.
// - Motion is applied incrementally from a One Euro-filtered palm pose, so a
//   change of scale (fine mode) mid-grab never causes a jump.
// - Holding a pinch with the OTHER hand engages precision mode (fineScale);
//   the HUD Fine toggle makes it sticky.
// - Orientation follows the palm only when Rotate is enabled (off by default):
//   the 5-DOF arm cannot reproduce arbitrary hand orientation.
// - On release the target rewinds ~0.1 s to remove finger-opening jitter.
// - Tracking loss releases the grab, cancels any pending preview, and requires
//   an open hand before the next grab. Nothing here can approve execution.
public class HandTeleopController : MonoBehaviour
{
    public DesktopTarget teleop;
    public Transform trackingOrigin;
    public bool rightHandDominant = true;
    [Header("Motion")]
    public float normalScale = 1.0f;
    public float fineScale = 0.25f;
    public float rotationScale = 1.0f;
    public bool rotationEnabled;
    public bool fineToggle;
    [Header("Pinch")]
    public float pinchStartMeters = 0.018f;
    public float pinchEndMeters = 0.032f;
    public float pinchDebounceSeconds = 0.06f;
    public float releaseRewindSeconds = 0.1f;
    [Header("Filtering")]
    public float filterMinCutoff = 1.0f;
    public float filterBeta = 4.0f;
    [Header("Workspace (robot base frame, metres)")]
    public float workspaceRadius = 0.34f;
    public float workspaceMinHeight = 0.0f;
    public float workspaceMaxHeight = 0.34f;
    [Header("Base placement")]
    public bool basePlacement;

    public static bool HandsActive { get; private set; }
    public bool DominantTracked { get; private set; }
    public bool Grabbing => grabbing;
    public bool FineActive { get; private set; }
    public bool WorkspaceClamped { get; private set; }
    public float PinchDistance { get; private set; }
    public string Status { get; private set; } = "Waiting for hand tracking";

    static readonly List<XRHandSubsystem> subsystems = new List<XRHandSubsystem>();
    XRHandSubsystem hands;
    readonly OneEuroFilter3 filter = new OneEuroFilter3();
    bool grabbing, requireOpen = true, pinchCandidate, otherPinch;
    float pinchSince;
    Vector3 lastHand;
    Quaternion lastHandRotation, smoothedRotation;
    struct Sample { public float time; public Vector3 local; public Quaternion rotation; }
    readonly Queue<Sample> history = new Queue<Sample>();
    const string BasePrefsKey = "tinyarm.robotBase";

    void Start()
    {
        var c = teleop != null ? teleop.Config : null;
        if (c != null) {
            if (c.dominantHand == "left") rightHandDominant = false;
            if (c.dominantHand == "right") rightHandDominant = true;
            normalScale = TeleopConfig.Pick(c.normalScale, normalScale);
            fineScale = TeleopConfig.Pick(c.fineScale, fineScale);
            pinchStartMeters = TeleopConfig.Pick(c.pinchStartMeters, pinchStartMeters);
            pinchEndMeters = Mathf.Max(pinchStartMeters + 0.005f, TeleopConfig.Pick(c.pinchEndMeters, pinchEndMeters));
            filterMinCutoff = TeleopConfig.Pick(c.filterMinCutoff, filterMinCutoff);
            filterBeta = TeleopConfig.Pick(c.filterBeta, filterBeta);
            workspaceRadius = TeleopConfig.Pick(c.workspaceRadius, workspaceRadius);
            workspaceMaxHeight = TeleopConfig.Pick(c.workspaceMaxHeight, workspaceMaxHeight);
        }
        LoadBasePose();
    }

    bool FindSubsystem()
    {
        if (hands != null && hands.running) return true;
        subsystems.Clear();
        SubsystemManager.GetSubsystems(subsystems);
        hands = null;
        foreach (var s in subsystems) if (s.running) { hands = s; break; }
        return hands != null;
    }

    static bool TryJoint(XRHand hand, XRHandJointID id, out Pose pose)
    {
        pose = default;
        return hand.isTracked && hand.GetJoint(id).TryGetPose(out pose);
    }

    // World-space fingertip used by the HUD for poke buttons.
    public bool TryGetIndexTip(bool dominant, out Vector3 world)
    {
        world = default;
        if (!FindSubsystem()) return false;
        var hand = dominant == rightHandDominant ? hands.rightHand : hands.leftHand;
        if (!TryJoint(hand, XRHandJointID.IndexTip, out Pose tip)) return false;
        world = Origin.TransformPoint(tip.position);
        return true;
    }

    Transform Origin => trackingOrigin != null ? trackingOrigin : transform;

    static float PinchGap(XRHand hand)
    {
        if (TryJoint(hand, XRHandJointID.ThumbTip, out Pose thumb) && TryJoint(hand, XRHandJointID.IndexTip, out Pose index))
            return Vector3.Distance(thumb.position, index.position);
        return float.PositiveInfinity;
    }

    void Update()
    {
        if (teleop == null) return;
        if (!FindSubsystem()) { HandsActive = false; DominantTracked = false; Status = "Hand tracking unavailable"; Release(false); return; }
        XRHand dominant = rightHandDominant ? hands.rightHand : hands.leftHand;
        XRHand other = rightHandDominant ? hands.leftHand : hands.rightHand;
        HandsActive = hands.rightHand.isTracked || hands.leftHand.isTracked;
        if (HandsActive) teleop.externalInput = true;

        float otherGap = PinchGap(other);
        otherPinch = otherPinch ? otherGap < pinchEndMeters : otherGap < pinchStartMeters;
        FineActive = fineToggle || otherPinch;

        bool palmOk = TryJoint(dominant, XRHandJointID.Palm, out Pose palm);
        DominantTracked = dominant.isTracked && palmOk;
        if (!DominantTracked) {
            if (grabbing) { Release(true); teleop.CancelPreview(); Status = "Tracking lost: target released, preview cancelled"; }
            else Status = HandsActive ? "Show your " + (rightHandDominant ? "right" : "left") + " hand" : "Waiting for hand tracking";
            requireOpen = true; pinchCandidate = false;
            return;
        }
        PinchDistance = PinchGap(dominant);
        bool pinched = grabbing || pinchCandidate ? PinchDistance < pinchEndMeters : PinchDistance < pinchStartMeters;
        if (!pinched) requireOpen = false;

        Vector3 handWorld = Origin.TransformPoint(palm.position);
        Quaternion handRotation = Origin.rotation * palm.rotation;
        float dt = Mathf.Max(Time.deltaTime, 1e-4f);

        if (!grabbing) {
            if (pinched && !requireOpen && teleop.PoseReady) {
                if (!pinchCandidate) { pinchCandidate = true; pinchSince = Time.time; }
                else if (Time.time - pinchSince >= pinchDebounceSeconds) BeginGrab(handWorld, handRotation);
            } else pinchCandidate = false;
            Status = !teleop.PoseReady ? "Waiting for Python / initial pose" :
                     requireOpen ? "Open your hand to re-arm" : basePlacement ? "Pinch to move the robot base" : "Pinch to grab the target";
            return;
        }
        if (!pinched) { Release(true); Status = "Released"; return; }

        filter.minCutoff = filterMinCutoff; filter.beta = filterBeta;
        Vector3 filtered = filter.Filter(handWorld, dt);
        smoothedRotation = Quaternion.Slerp(smoothedRotation, handRotation, 1f - Mathf.Exp(-dt * 2f * Mathf.PI * 4f));
        Vector3 delta = filtered - lastHand;
        Quaternion rotationDelta = smoothedRotation * Quaternion.Inverse(lastHandRotation);
        lastHand = filtered; lastHandRotation = smoothedRotation;
        float scale = FineActive ? fineScale : normalScale;

        if (basePlacement) { MoveBase(delta, rotationDelta); Status = "Placing robot base (commands frozen)"; return; }

        Transform target = teleop.target;
        target.position += delta * scale;
        if (rotationEnabled) {
            float rotationAmount = rotationScale * (FineActive ? 0.5f : 1f);
            target.rotation = Quaternion.Slerp(Quaternion.identity, rotationDelta, rotationAmount) * target.rotation;
        }
        ClampToWorkspace();
        Remember();
        Status = (FineActive ? "PRECISION " : "") + "Moving target" + (rotationEnabled ? " + rotation" : "") +
                 (WorkspaceClamped ? " (workspace limit)" : "");
    }

    void BeginGrab(Vector3 handWorld, Quaternion handRotation)
    {
        grabbing = true;
        filter.Reset(handWorld);
        lastHand = handWorld;
        lastHandRotation = smoothedRotation = handRotation;
        history.Clear();
        if (!basePlacement) { teleop.CancelPreview(); Remember(); }
    }

    void Release(bool rewind)
    {
        if (!grabbing) return;
        grabbing = false;
        pinchCandidate = false;
        if (basePlacement) { SaveBasePose(); return; }
        if (rewind && history.Count > 0) {
            // Restore the pose from just before fingers started opening.
            float cutoff = Time.time - releaseRewindSeconds;
            Sample chosen = history.Peek();
            foreach (var s in history) { if (s.time <= cutoff) chosen = s; else break; }
            SetLocal(chosen.local, chosen.rotation);
        }
        history.Clear();
    }

    void Remember()
    {
        Transform b = teleop.robotBase;
        Transform t = teleop.target;
        history.Enqueue(new Sample { time = Time.time,
            local = b == null ? t.position : b.InverseTransformPoint(t.position),
            rotation = b == null ? t.rotation : Quaternion.Inverse(b.rotation) * t.rotation });
        while (history.Count > 0 && Time.time - history.Peek().time > 0.5f) history.Dequeue();
    }

    void SetLocal(Vector3 local, Quaternion rotation)
    {
        Transform b = teleop.robotBase;
        teleop.target.position = b == null ? local : b.TransformPoint(local);
        teleop.target.rotation = b == null ? rotation : b.rotation * rotation;
    }

    void ClampToWorkspace()
    {
        Transform b = teleop.robotBase;
        Vector3 local = b == null ? teleop.target.position : b.InverseTransformPoint(teleop.target.position);
        Vector3 clamped = local;
        clamped.y = Mathf.Clamp(clamped.y, workspaceMinHeight, workspaceMaxHeight);
        if (clamped.magnitude > workspaceRadius) clamped = clamped.normalized * workspaceRadius;
        WorkspaceClamped = (clamped - local).sqrMagnitude > 1e-10f;
        if (WorkspaceClamped) teleop.target.position = b == null ? clamped : b.TransformPoint(clamped);
    }

    // Base placement: translate freely, rotate about vertical only. The target is
    // kept fixed in the base frame, so robot coordinates do not change.
    void MoveBase(Vector3 delta, Quaternion rotationDelta)
    {
        Transform b = teleop.robotBase;
        if (b == null) return;
        Vector3 targetLocal = b.InverseTransformPoint(teleop.target.position);
        Quaternion targetLocalRotation = Quaternion.Inverse(b.rotation) * teleop.target.rotation;
        float yaw = rotationDelta.eulerAngles.y;
        if (yaw > 180f) yaw -= 360f;
        b.position += delta;
        b.rotation = Quaternion.AngleAxis(yaw, Vector3.up) * b.rotation;
        teleop.target.position = b.TransformPoint(targetLocal);
        teleop.target.rotation = b.rotation * targetLocalRotation;
    }

    void SaveBasePose()
    {
        Transform b = teleop.robotBase;
        if (b == null) return;
        Vector3 p = Origin.InverseTransformPoint(b.position);
        float yaw = (Quaternion.Inverse(Origin.rotation) * b.rotation).eulerAngles.y;
        PlayerPrefs.SetString(BasePrefsKey, string.Format(System.Globalization.CultureInfo.InvariantCulture, "{0:R},{1:R},{2:R},{3:R}", p.x, p.y, p.z, yaw));
        PlayerPrefs.Save();
    }

    void LoadBasePose()
    {
        Transform b = teleop != null ? teleop.robotBase : null;
        string saved = PlayerPrefs.GetString(BasePrefsKey, "");
        var parts = saved.Split(',');
        if (b == null || parts.Length != 4) return;
        var v = new float[4];
        for (int i = 0; i < 4; i++)
            if (!float.TryParse(parts[i], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out v[i])) return;
        Vector3 targetLocal = b.InverseTransformPoint(teleop.target.position);
        Quaternion targetLocalRotation = Quaternion.Inverse(b.rotation) * teleop.target.rotation;
        b.position = Origin.TransformPoint(new Vector3(v[0], v[1], v[2]));
        b.rotation = Origin.rotation * Quaternion.Euler(0, v[3], 0);
        teleop.target.position = b.TransformPoint(targetLocal);
        teleop.target.rotation = b.rotation * targetLocalRotation;
    }

    public void ResetBasePose() { PlayerPrefs.DeleteKey(BasePrefsKey); }

    void OnDisable() { Release(false); HandsActive = false; }
    void OnApplicationPause(bool paused) { if (paused) { Release(false); requireOpen = true; teleop?.CancelPreview(); } }
}
