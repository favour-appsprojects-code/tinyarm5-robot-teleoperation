using System.IO;
using System.Xml;
using UnityEditor.Android;
using UnityEngine;

// Safety net after Gradle project generation: make sure the Quest manifest
// declares hand tracking and passthrough (normally added by the Meta XR
// feature from OVRProjectConfig). Adds only what is missing; never removes.
public class QuestManifestCheck : IPostGenerateGradleAndroidProject
{
    public int callbackOrder => 10000; // After Unity/Meta manifest processors.
    const string AndroidNs = "http://schemas.android.com/apk/res/android";

    public void OnPostGenerateGradleAndroidProject(string path)
    {
        string manifest = Path.Combine(path, "src", "main", "AndroidManifest.xml");
        if (!File.Exists(manifest)) { Debug.LogWarning("[TinyARM] Manifest not found at " + manifest); return; }
        var doc = new XmlDocument();
        doc.Load(manifest);
        var root = doc.DocumentElement;
        bool changed = false;
        changed |= Ensure(doc, root, "uses-permission", "com.oculus.permission.HAND_TRACKING", null);
        changed |= Ensure(doc, root, "uses-feature", "oculus.software.handtracking", "false");
        changed |= Ensure(doc, root, "uses-feature", "com.oculus.feature.PASSTHROUGH", "true");
        changed |= Ensure(doc, root, "uses-permission", "android.permission.INTERNET", null);
        if (changed) { doc.Save(manifest); Debug.Log("[TinyARM] Added missing Quest manifest entries in " + manifest); }
        else Debug.Log("[TinyARM] Quest manifest already declares hand tracking, passthrough and internet.");
    }

    static bool Ensure(XmlDocument doc, XmlElement root, string element, string name, string required)
    {
        foreach (XmlNode node in root.GetElementsByTagName(element))
            if (node.Attributes?["name", AndroidNs]?.Value == name) return false;
        var e = doc.CreateElement(element);
        e.SetAttribute("name", AndroidNs, name);
        if (required != null) e.SetAttribute("required", AndroidNs, required);
        root.AppendChild(e);
        return true;
    }
}
