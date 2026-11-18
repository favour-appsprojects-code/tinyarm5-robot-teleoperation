using System;
using System.IO;
using UnityEngine;

// Runtime settings that change between networks/users, loaded without a rebuild.
// On Quest: adb push teleop_config.json /sdcard/Android/data/<package>/files/
// Empty/zero fields keep the scene's serialized values.
[Serializable]
public class TeleopConfig
{
    public string serverAddress = "";      // "auto" = LAN discovery; "" = keep scene value
    public int serverPort = 0;             // 0 = keep scene value (5006)
    public string dominantHand = "";       // "right" or "left"
    public float normalScale = 0f;         // hand-to-target motion scale
    public float fineScale = 0f;           // precision-mode motion scale
    public float pinchStartMeters = 0f;    // thumb-index distance that starts a pinch
    public float pinchEndMeters = 0f;      // larger distance that ends it (hysteresis)
    public float filterMinCutoff = 0f;     // One Euro filter, Hz
    public float filterBeta = 0f;
    public float workspaceRadius = 0f;     // metres from robot base
    public float workspaceMaxHeight = 0f;

    public const string FileName = "teleop_config.json";
    public static string FilePath => Path.Combine(Application.persistentDataPath, FileName);

    public static TeleopConfig Load(out string source)
    {
        source = "scene defaults";
        try
        {
            if (File.Exists(FilePath))
            {
                var config = JsonUtility.FromJson<TeleopConfig>(File.ReadAllText(FilePath));
                source = FilePath;
                return config ?? new TeleopConfig();
            }
            // Leave a template next to where the real file would go.
            string example = Path.Combine(Application.persistentDataPath, "teleop_config.example.json");
            if (!File.Exists(example))
                File.WriteAllText(example, JsonUtility.ToJson(new TeleopConfig {
                    serverAddress = "auto", serverPort = 5006, dominantHand = "right", normalScale = 1f,
                    fineScale = 0.25f, pinchStartMeters = 0.018f, pinchEndMeters = 0.032f,
                    filterMinCutoff = 1.0f, filterBeta = 4f, workspaceRadius = 0.34f, workspaceMaxHeight = 0.34f }, true));
        }
        catch (Exception ex) { source = "config error: " + ex.Message; }
        return new TeleopConfig();
    }

    public static float Pick(float configured, float fallback) => configured > 0f ? configured : fallback;
}
