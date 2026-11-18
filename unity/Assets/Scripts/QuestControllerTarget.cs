using UnityEngine;
using UnityEngine.XR;

// Controller FALLBACK for the UDP target (hands are primary, see
// HandTeleopController). Inactive while hands are tracked. No hardware-enable control.
public class QuestControllerTarget : MonoBehaviour
{
    public DesktopTarget teleoperation;
    public Transform trackingOrigin;
    public Transform headCamera;
    public float movementScale = 0.5f;
    bool gripWasDown, previewWasDown, confirmWasDown, trackingWasValid, triggerWasDown;
    bool requireRelease = true;
    Vector3 controllerStart, targetStart;
    Quaternion controllerRotationStart, targetRotationStart;

    void OnEnable() { if (teleoperation != null) teleoperation.externalInput = true; }
    void OnDisable() {
        if (teleoperation != null) { teleoperation.externalInput = false; teleoperation.DisableOutput(); }
        requireRelease = true;
    }
    void Update()
    {
        if (teleoperation == null || trackingOrigin == null) return;
        teleoperation.externalInput = true;
        if (HandTeleopController.HandsActive) { requireRelease = true; gripWasDown = false; return; }
        var head = InputDevices.GetDeviceAtXRNode(XRNode.Head);
        if (headCamera != null && headCamera.GetComponent<UnityEngine.SpatialTracking.TrackedPoseDriver>() == null && head.TryGetFeatureValue(CommonUsages.devicePosition,out Vector3 hp) &&
            head.TryGetFeatureValue(CommonUsages.deviceRotation,out Quaternion hr)) {
            headCamera.localPosition = hp;
            headCamera.localRotation = hr;
        }
        var right = InputDevices.GetDeviceAtXRNode(XRNode.RightHand);
        bool valid = right.isValid && right.TryGetFeatureValue(CommonUsages.isTracked,out bool tracked) && tracked;
        if (!valid || !right.TryGetFeatureValue(CommonUsages.devicePosition,out Vector3 p) ||
            !right.TryGetFeatureValue(CommonUsages.deviceRotation,out Quaternion rotation)) {
            // Tracking loss cancels a pending preview; it does not permanently disable output.
            if (trackingWasValid) teleoperation.CancelPreview();
            trackingWasValid = false; requireRelease = true; gripWasDown = false;
            return;
        }
        trackingWasValid = true;
        if (!teleoperation.PoseReady) { requireRelease = true; return; }
        right.TryGetFeatureValue(CommonUsages.gripButton,out bool grip);
        right.TryGetFeatureValue(CommonUsages.primaryButton,out bool preview);
        right.TryGetFeatureValue(CommonUsages.secondaryButton,out bool confirm);
        right.TryGetFeatureValue(CommonUsages.trigger,out float trigger);
        Vector3 world = trackingOrigin.TransformPoint(p);
        Quaternion worldRotation = trackingOrigin.rotation * rotation;
        // Reconnection must not turn already-held A/B buttons into new approvals.
        if (requireRelease) {
            gripWasDown=grip; previewWasDown=preview; confirmWasDown=confirm;
            if (!grip && !preview && !confirm) requireRelease=false;
            return;
        }
        if (grip && !gripWasDown && !requireRelease && teleoperation.PoseReady) {
            teleoperation.CancelPreview();
            controllerStart = world; controllerRotationStart = worldRotation;
            targetStart = teleoperation.target.position; targetRotationStart = teleoperation.target.rotation;
        }
        if (grip && !requireRelease && teleoperation.PoseReady) {
            teleoperation.target.position = targetStart + movementScale*(world-controllerStart);
            teleoperation.target.rotation = worldRotation * Quaternion.Inverse(controllerRotationStart) * targetRotationStart;
        }
        // Gripper changes only on trigger edges, so the HUD buttons are not overridden.
        if (trigger > 0.7f && !triggerWasDown) teleoperation.SetGripper("closed");
        if (trigger < 0.3f && triggerWasDown) teleoperation.SetGripper("open");
        triggerWasDown = trigger > 0.7f || (triggerWasDown && trigger >= 0.3f);
        if (preview && !previewWasDown && !grip) teleoperation.RequestPreview();
        if (confirm && !confirmWasDown && !grip) teleoperation.ConfirmPreview();
        var left = InputDevices.GetDeviceAtXRNode(XRNode.LeftHand);
        if (left.TryGetFeatureValue(CommonUsages.menuButton,out bool stop) && stop) teleoperation.DisableOutput();
        if (left.TryGetFeatureValue(CommonUsages.primaryButton,out bool x) && x) teleoperation.DisableOutput();
        gripWasDown = grip; previewWasDown = preview; confirmWasDown = confirm;
    }
    void OnApplicationPause(bool paused) { if (paused && teleoperation != null) { teleoperation.DisableOutput(); requireRelease=true; } }
}
