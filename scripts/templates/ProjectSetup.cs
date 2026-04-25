using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.PackageManager;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// Temporary editor script executed via -executeMethod in batchmode.
/// Reads config from UNITY_INIT_CONFIG env var (JSON file path).
/// Supports two modes set via UNITY_INIT_PHASE env var:
///   "install"   — install Unity registry packages, then exit
///   "configure" — configure PlayerSettings, input system, Rider, URP
/// Deletes itself after the configure phase.
/// </summary>
public static class ProjectSetup
{
    [Serializable]
    private class Config
    {
        public string projectName;
        public string companyName;
        public int inputHandler; // 0 = Old, 1 = New, 2 = Both
    }

    public static void Run()
    {
        try
        {
            var phase = Environment.GetEnvironmentVariable("UNITY_INIT_PHASE") ?? "configure";
            var configPath = Environment.GetEnvironmentVariable("UNITY_INIT_CONFIG");
            if (string.IsNullOrEmpty(configPath) || !File.Exists(configPath))
            {
                Debug.LogError("[ProjectSetup] Config file not found: " + configPath);
                EditorApplication.Exit(1);
                return;
            }

            var json = File.ReadAllText(configPath);
            var config = JsonUtility.FromJson<Config>(json);

            if (phase == "install")
                RunInstall(config);
            else
                RunConfigure(config);
        }
        catch (Exception ex)
        {
            Debug.LogError("[ProjectSetup] Failed: " + ex.Message + "\n" + ex.StackTrace);
            EditorApplication.Exit(1);
        }
    }

    // =======================================================================
    // Phase 1: Install packages
    // =======================================================================

    private static void RunInstall(Config config)
    {
        InstallPackage("com.unity.render-pipelines.universal");
        InstallPackage("com.unity.ide.rider");

        if (config.inputHandler > 0) // New or Both
            InstallPackage("com.unity.inputsystem");

        Debug.Log("[ProjectSetup] Package installation complete.");
    }

    private static void InstallPackage(string packageId)
    {
        var request = Client.Add(packageId);
        while (!request.IsCompleted)
            System.Threading.Thread.Sleep(100);

        if (request.Status == StatusCode.Success)
            Debug.Log($"[ProjectSetup] Installed {packageId}");
        else if (request.Error != null)
            Debug.LogWarning($"[ProjectSetup] {packageId}: {request.Error.message}");
    }

    // =======================================================================
    // Phase 2: Configure settings
    // =======================================================================

    private static void RunConfigure(Config config)
    {
        ConfigurePlayerSettings(config);
        ConfigureInputSystem(config);
        SetRiderAsExternalEditor();
        SetupURP();

        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        Debug.Log("[ProjectSetup] All settings configured successfully.");
        CleanUp();
    }

    private static void ConfigurePlayerSettings(Config config)
    {
        PlayerSettings.productName = config.projectName;
        PlayerSettings.companyName = config.companyName;

        var bundleId = $"com.{config.companyName.ToLower()}.{config.projectName.ToLower()}";
        PlayerSettings.SetApplicationIdentifier(BuildTargetGroup.Android, bundleId);
        PlayerSettings.SetApplicationIdentifier(BuildTargetGroup.iOS, bundleId);
        PlayerSettings.SetApplicationIdentifier(BuildTargetGroup.Standalone, bundleId);

        Debug.Log($"[ProjectSetup] PlayerSettings: {config.companyName} / {config.projectName}");
    }

    private static void ConfigureInputSystem(Config config)
    {
        var playerSettings = Resources.FindObjectsOfTypeAll<PlayerSettings>();
        if (playerSettings.Length == 0)
        {
            Debug.LogWarning("[ProjectSetup] Could not find PlayerSettings object");
            return;
        }

        var so = new SerializedObject(playerSettings[0]);
        var prop = so.FindProperty("activeInputHandler");
        if (prop != null)
        {
            prop.intValue = config.inputHandler;
            so.ApplyModifiedPropertiesWithoutUndo();
            var names = new[] { "Old (Input Manager)", "New (Input System)", "Both" };
            Debug.Log($"[ProjectSetup] Input handler set to: {names[config.inputHandler]}");
        }
        else
        {
            Debug.LogWarning("[ProjectSetup] Could not find activeInputHandler property");
        }
    }

    private static void SetRiderAsExternalEditor()
    {
        var searchPaths = new[]
        {
            "/Applications/Rider.app",
            "/Applications/JetBrains Rider.app",
        };

        string riderPath = searchPaths.FirstOrDefault(Directory.Exists);

        // ~/Applications (JetBrains Toolbox default on macOS)
        if (riderPath == null)
        {
            var userApps = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                "Applications"
            );
            if (Directory.Exists(userApps))
            {
                riderPath = Directory.GetDirectories(userApps, "Rider*.app")
                    .OrderByDescending(d => d)
                    .FirstOrDefault();
            }
        }

        // ~/Library/Application Support/JetBrains/Toolbox/apps (older Toolbox layout)
        if (riderPath == null)
        {
            var toolboxBase = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                "Library/Application Support/JetBrains/Toolbox/apps"
            );
            if (Directory.Exists(toolboxBase))
            {
                riderPath = Directory.GetDirectories(toolboxBase, "*.app", SearchOption.AllDirectories)
                    .Where(d => d.Contains("Rider") && d.EndsWith(".app"))
                    .OrderByDescending(d => d)
                    .FirstOrDefault();
            }
        }

        if (riderPath != null)
        {
            EditorPrefs.SetString("kScriptsDefaultApp", riderPath);
            Debug.Log($"[ProjectSetup] External editor set to: {riderPath}");
        }
        else
        {
            Debug.LogWarning("[ProjectSetup] Rider not found on disk, skipping external editor setup");
        }
    }

    private static void SetupURP()
    {
        var settingsDir = "Assets/Settings";
        if (!AssetDatabase.IsValidFolder(settingsDir))
            AssetDatabase.CreateFolder("Assets", "Settings");

        var urpAssetType = Type.GetType(
            "UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset, " +
            "Unity.RenderPipelines.Universal.Runtime"
        );
        if (urpAssetType == null)
        {
            Debug.LogWarning("[ProjectSetup] URP types not found. " +
                             "URP pipeline asset must be configured manually.");
            return;
        }

        var rendererDataType = Type.GetType(
            "UnityEngine.Rendering.Universal.UniversalRendererData, " +
            "Unity.RenderPipelines.Universal.Runtime"
        );

        // --- Create local renderer data (package ships one but it's read-only) ---
        string rendererDataPath = Path.Combine(settingsDir, "UniversalRendererData.asset");
        if (rendererDataType != null)
        {
            var rendererData = ScriptableObject.CreateInstance(rendererDataType);
            AssetDatabase.CreateAsset(rendererData, rendererDataPath);
        }
        else
        {
            Debug.LogWarning("[ProjectSetup] UniversalRendererData type not found");
            rendererDataPath = null;
        }

        // --- Create local pipeline asset ---
        string urpAssetPath = Path.Combine(settingsDir, "UniversalRenderPipelineAsset.asset");
        var urpAsset = ScriptableObject.CreateInstance(urpAssetType);
        AssetDatabase.CreateAsset(urpAsset, urpAssetPath);

        Debug.Log($"[ProjectSetup] URP assets: {urpAssetPath}, {rendererDataPath}");

        // --- Wire renderer into pipeline asset ---
        if (rendererDataPath != null)
        {
            var rendererAsset = AssetDatabase.LoadAssetAtPath<ScriptableObject>(rendererDataPath);
            if (rendererAsset != null)
            {
                var so = new SerializedObject(
                    AssetDatabase.LoadAssetAtPath<ScriptableObject>(urpAssetPath));
                var rendererListProp = so.FindProperty("m_RendererDataList");
                if (rendererListProp != null)
                {
                    rendererListProp.arraySize = 1;
                    rendererListProp.GetArrayElementAtIndex(0).objectReferenceValue = rendererAsset;
                    so.ApplyModifiedPropertiesWithoutUndo();
                    Debug.Log("[ProjectSetup] Renderer data wired into pipeline asset");
                }
                else
                {
                    Debug.LogWarning("[ProjectSetup] Could not find m_RendererDataList property");
                }
            }
        }

        // --- Assign to graphics + quality settings ---
        var pipelineAsset = AssetDatabase.LoadAssetAtPath<RenderPipelineAsset>(urpAssetPath);
        if (pipelineAsset != null)
        {
            GraphicsSettings.defaultRenderPipeline = pipelineAsset;

            var qualityCount = QualitySettings.names.Length;
            for (int i = 0; i < qualityCount; i++)
            {
                QualitySettings.SetQualityLevel(i, false);
                QualitySettings.renderPipeline = pipelineAsset;
            }

            Debug.Log("[ProjectSetup] URP assigned to GraphicsSettings and all quality levels");
        }
        else
        {
            Debug.LogWarning("[ProjectSetup] Could not load URP asset for assignment");
        }
    }

    private static void CleanUp()
    {
        var scriptPath = "Assets/Editor/ProjectSetup.cs";
        if (File.Exists(scriptPath))
        {
            AssetDatabase.DeleteAsset(scriptPath);
            Debug.Log("[ProjectSetup] Cleaned up setup script");
        }
    }
}
