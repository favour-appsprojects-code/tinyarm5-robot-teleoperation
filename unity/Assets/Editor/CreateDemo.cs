using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class CreateDemo
{
    [MenuItem("TinyARM/Create Desktop Demo")]
    public static void Build()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var camera = new GameObject("Camera").AddComponent<Camera>();
        camera.tag = "MainCamera";
        camera.transform.position = new Vector3(0.42f,0.36f,-0.48f);
        camera.transform.LookAt(new Vector3(0,0.1f,0.08f));
        camera.nearClipPlane = 0.01f;
        camera.backgroundColor = new Color(0.08f,0.1f,0.14f);
        camera.clearFlags = CameraClearFlags.SolidColor;
        var light = new GameObject("Light").AddComponent<Light>();
        light.type = LightType.Directional;
        light.transform.rotation = Quaternion.Euler(45,-30,0);
        var floor = GameObject.CreatePrimitive(PrimitiveType.Cube);
        floor.name = "Reference plane (not a reachability guarantee)";
        floor.transform.position = new Vector3(0,-0.008f,0);
        floor.transform.localScale = new Vector3(0.6f,0.01f,0.6f);
        floor.GetComponent<Renderer>().sharedMaterial = Material(Color.gray);
        Axis("Robot X / Unity X", new Vector3(0.15f,0,0), new Vector3(0.3f,0.003f,0.003f), Color.red);
        Axis("Robot Z / Unity Y", new Vector3(0,0.15f,0), new Vector3(0.003f,0.3f,0.003f), Color.blue);
        Axis("Robot -Y / Unity Z", new Vector3(0,0,0.15f), new Vector3(0.003f,0.003f,0.3f), Color.green);
        var target = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        target.name = "UDP Target";
        target.transform.position = new Vector3(0,0.15f,0.12f);
        target.transform.localScale = Vector3.one * 0.015f;
        target.GetComponent<Renderer>().sharedMaterial = Material(Color.yellow);
        new GameObject("Simulation UDP").AddComponent<DesktopTarget>().target = target.transform;
        System.IO.Directory.CreateDirectory("Assets/Scenes");
        EditorSceneManager.SaveScene(scene,"Assets/Scenes/DesktopDemo.unity");
        EditorBuildSettings.scenes = new [] { new EditorBuildSettingsScene("Assets/Scenes/DesktopDemo.unity",true) };
        // Use Unity's built-in keyboard Input API for this desktop-only milestone.
        var settings = new SerializedObject(AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/ProjectSettings.asset")[0]);
        var input = settings.FindProperty("activeInputHandler");
        if (input != null) { input.intValue = 0; settings.ApplyModifiedProperties(); }
    }
    static Material Material(Color color)
    {
        System.IO.Directory.CreateDirectory("Assets/Materials");
        var path = $"Assets/Materials/Color_{ColorUtility.ToHtmlStringRGB(color)}.mat";
        var material = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (material == null) {
            material = new Material(Shader.Find("Standard")); material.color = color;
            AssetDatabase.CreateAsset(material, path);
        }
        return material;
    }
    static void Axis(string name, Vector3 position, Vector3 scale, Color color)
    {
        var axis = GameObject.CreatePrimitive(PrimitiveType.Cube); axis.name = name;
        axis.transform.position = position; axis.transform.localScale = scale;
        axis.GetComponent<Renderer>().sharedMaterial = Material(color);
    }
}
