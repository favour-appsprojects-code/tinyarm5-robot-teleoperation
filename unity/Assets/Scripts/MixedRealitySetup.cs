using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;

// Runtime MR bootstrap: floor-level tracking origin and a transparent camera
// background so Meta passthrough (OVRManager + OVRPassthroughLayer, added by
// TinyARM > Quest MR setup) shows behind virtual content.
public class MixedRealitySetup : MonoBehaviour
{
    public Camera xrCamera;
    bool originSet;
    float giveUpAt;

    void Start()
    {
        if (xrCamera == null) xrCamera = Camera.main;
        if (xrCamera != null) {
            xrCamera.clearFlags = CameraClearFlags.SolidColor;
            xrCamera.backgroundColor = new Color(0, 0, 0, 0);
            xrCamera.nearClipPlane = 0.03f;
        }
        giveUpAt = Time.unscaledTime + 10f;
        Debug.Log($"[TinyARM] XR device active={XRSettings.isDeviceActive} name='{XRSettings.loadedDeviceName}' config={TeleopConfig.FilePath}");
    }

    void Update()
    {
        if (originSet || Time.unscaledTime > giveUpAt) return;
        var inputs = new List<XRInputSubsystem>();
        SubsystemManager.GetSubsystems(inputs);
        foreach (var input in inputs)
            if (input.running && input.TrySetTrackingOriginMode(TrackingOriginModeFlags.Floor)) originSet = true;
        if (originSet) Debug.Log("[TinyARM] Floor tracking origin set");
    }
}
