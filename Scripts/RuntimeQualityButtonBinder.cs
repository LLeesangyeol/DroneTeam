using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

public class RuntimeQualityButtonBinder : MonoBehaviour
{
    public UniversalRenderPipelineAsset urp;
    public Volume globalVolume;

    Terrain[] terrains;

    void Awake()
    {
        terrains = Terrain.activeTerrains;
    }

    void ApplyTerrain(System.Action<Terrain> act)
    {
        if (terrains == null) return;
        foreach (var t in terrains)
            if (t) act(t);
    }

    public void SetHigh()
    {
        urp.renderScale = 1.0f;
        urp.msaaSampleCount = 4;
        urp.shadowDistance = 120f;
        urp.shadowCascadeCount = 4;
        urp.supportsHDR = true;
        urp.supportsCameraDepthTexture = true;
        urp.supportsCameraOpaqueTexture = true;

        QualitySettings.lodBias = 2.0f;
        QualitySettings.vSyncCount = 1;
        Application.targetFrameRate = -1;

        if (globalVolume) globalVolume.enabled = true;

        ApplyTerrain(t =>
        {
            t.detailObjectDistance = 100f;
            t.treeDistance = 1200f;
        });
    }

    public void SetMedium()
    {
        urp.renderScale = 0.85f;
        urp.msaaSampleCount = 2;
        urp.shadowDistance = 60f;
        urp.shadowCascadeCount = 2;
        urp.supportsHDR = false;
        urp.supportsCameraDepthTexture = true;
        urp.supportsCameraOpaqueTexture = false;

        QualitySettings.lodBias = 1.2f;
        QualitySettings.vSyncCount = 0;
        Application.targetFrameRate = 60;

        if (globalVolume) globalVolume.enabled = true;

        ApplyTerrain(t =>
        {
            t.detailObjectDistance = 50f;
            t.treeDistance = 600f;
        });
    }

    public void SetLow()
    {
        urp.renderScale = 0.75f;
        urp.msaaSampleCount = 1;
        urp.shadowDistance = 30f;
        urp.shadowCascadeCount = 1;
        urp.supportsHDR = false;
        urp.supportsCameraDepthTexture = false;
        urp.supportsCameraOpaqueTexture = false;

        QualitySettings.lodBias = 0.8f;
        QualitySettings.vSyncCount = 0;
        Application.targetFrameRate = 45;

        if (globalVolume) globalVolume.enabled = false;

        ApplyTerrain(t =>
        {
            t.detailObjectDistance = 20f;
            t.treeDistance = 300f;
        });
    }

    public void SetLowest()
    {
        urp.renderScale = 0.65f;
        urp.msaaSampleCount = 1;
        urp.shadowDistance = 0f;
        urp.shadowCascadeCount = 1;
        urp.supportsHDR = false;
        urp.supportsCameraDepthTexture = false;
        urp.supportsCameraOpaqueTexture = false;

        QualitySettings.lodBias = 0.6f;
        QualitySettings.vSyncCount = 0;
        Application.targetFrameRate = 30;

        if (globalVolume) globalVolume.enabled = false;

        ApplyTerrain(t =>
        {
            t.detailObjectDistance = 0f;
            t.treeDistance = 150f;
        });
    }
}
