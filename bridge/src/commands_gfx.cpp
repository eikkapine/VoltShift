// VoltShift bridge — 3D graphics settings (per-GPU driver features).
//
// gfx.get returns one object per feature with a "supported" flag plus the
// current state; gfx.set takes {"feature":"<name>", ...} and applies only the
// keys present. Enum-typed values cross the wire as raw ints — the Python
// side owns the human-readable names (see voltshift/adlxenums.py).
#include "rpc.h"

using namespace adlx;

namespace voltshift {

namespace {

// ── per-feature getters ──────────────────────────────────────────────────────

json GetAntiLag(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DAntiLagPtr al;
    if (ADLX_FAILED(session.GfxServices()->GetAntiLag(gpu, &al)) || !al)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    al->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    al->IsEnabled(&enabled);
    json out = {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};

    IADLX3DAntiLag1Ptr al1;
    if (ADLX_SUCCEEDED(al->QueryInterface(IADLX3DAntiLag1::IID(), reinterpret_cast<void**>(&al1))) && al1)
    {
        ADLX_ANTILAG_STATE level = ANTILAG;
        if (ADLX_SUCCEEDED(al1->GetLevel(&level)))
            out["level"] = static_cast<int>(level);  // 0=AntiLag, 1=AntiLag Next
    }
    return out;
}

json GetChill(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DChillPtr chill;
    if (ADLX_FAILED(session.GfxServices()->GetChill(gpu, &chill)) || !chill)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    chill->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    chill->IsEnabled(&enabled);
    adlx_int minFps = 0, maxFps = 0;
    ADLX_IntRange range = {};
    chill->GetMinFPS(&minFps);
    chill->GetMaxFPS(&maxFps);
    chill->GetFPSRange(&range);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)},
            {"minFps", minFps}, {"maxFps", maxFps},
            {"fpsRange", {{"min", range.minValue}, {"max", range.maxValue}, {"step", range.step}}}};
}

json GetBoost(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DBoostPtr boost;
    if (ADLX_FAILED(session.GfxServices()->GetBoost(gpu, &boost)) || !boost)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    boost->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    boost->IsEnabled(&enabled);
    adlx_int res = 0;
    ADLX_IntRange range = {};
    boost->GetResolution(&res);
    boost->GetResolutionRange(&range);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)},
            {"minResolutionPct", res},
            {"resolutionRange", {{"min", range.minValue}, {"max", range.maxValue}, {"step", range.step}}}};
}

json GetImageSharpening(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DImageSharpeningPtr ris;
    if (ADLX_FAILED(session.GfxServices()->GetImageSharpening(gpu, &ris)) || !ris)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    ris->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    ris->IsEnabled(&enabled);
    adlx_int sharpness = 0;
    ADLX_IntRange range = {};
    ris->GetSharpness(&sharpness);
    ris->GetSharpnessRange(&range);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)},
            {"sharpness", sharpness},
            {"sharpnessRange", {{"min", range.minValue}, {"max", range.maxValue}, {"step", range.step}}}};
}

json GetImageSharpenDesktop(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DSettingsServices2Ptr svc2 = session.GfxServices2();
    if (!svc2)
        return {{"supported", false}};
    IADLX3DImageSharpenDesktopPtr isd;
    if (ADLX_FAILED(svc2->GetImageSharpenDesktop(gpu, &isd)) || !isd)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    isd->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    isd->IsEnabled(&enabled);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
}

json GetEnhancedSync(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DEnhancedSyncPtr es;
    if (ADLX_FAILED(session.GfxServices()->GetEnhancedSync(gpu, &es)) || !es)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    es->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    es->IsEnabled(&enabled);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
}

json GetVSync(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DWaitForVerticalRefreshPtr vsync;
    if (ADLX_FAILED(session.GfxServices()->GetWaitForVerticalRefresh(gpu, &vsync)) || !vsync)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    vsync->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    vsync->IsEnabled(&enabled);
    ADLX_WAIT_FOR_VERTICAL_REFRESH_MODE mode = WFVR_ALWAYS_OFF;
    vsync->GetMode(&mode);
    // mode: 0=always off, 1=off unless app specifies, 2=on unless app specifies, 3=always on
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)}, {"mode", static_cast<int>(mode)}};
}

json GetFrtc(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DFrameRateTargetControlPtr frtc;
    if (ADLX_FAILED(session.GfxServices()->GetFrameRateTargetControl(gpu, &frtc)) || !frtc)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    frtc->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    frtc->IsEnabled(&enabled);
    adlx_int fps = 0;
    ADLX_IntRange range = {};
    frtc->GetFPS(&fps);
    frtc->GetFPSRange(&range);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)},
            {"fps", fps},
            {"fpsRange", {{"min", range.minValue}, {"max", range.maxValue}, {"step", range.step}}}};
}

json GetRsr(Session& session)
{
    IADLX3DRadeonSuperResolutionPtr rsr;
    if (ADLX_FAILED(session.GfxServices()->GetRadeonSuperResolution(&rsr)) || !rsr)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    rsr->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    rsr->IsEnabled(&enabled);
    adlx_int sharpness = 0;
    ADLX_IntRange range = {};
    rsr->GetSharpness(&sharpness);
    rsr->GetSharpnessRange(&range);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)},
            {"sharpness", sharpness},
            {"sharpnessRange", {{"min", range.minValue}, {"max", range.maxValue}, {"step", range.step}}}};
}

json GetAfmf(Session& session)
{
    IADLX3DSettingsServices1Ptr svc1 = session.GfxServices1();
    if (!svc1)
        return {{"supported", false}};
    IADLX3DAMDFluidMotionFramesPtr afmf;
    if (ADLX_FAILED(svc1->GetAMDFluidMotionFrames(&afmf)) || !afmf)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    afmf->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    afmf->IsEnabled(&enabled);
    json out = {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};

    IADLX3DAMDFluidMotionFrames1Ptr afmf1;
    if (ADLX_SUCCEEDED(afmf->QueryInterface(IADLX3DAMDFluidMotionFrames1::IID(), reinterpret_cast<void**>(&afmf1))) && afmf1)
    {
        ADLX_AFMF_SEARCH_MODE_TYPE search = {};
        ADLX_AFMF_PERFORMANCE_MODE_TYPE perf = {};
        ADLX_AFMF_FAST_MOTION_RESP fastMotion = {};
        if (ADLX_SUCCEEDED(afmf1->GetSearchMode(&search)))
            out["searchMode"] = static_cast<int>(search);
        if (ADLX_SUCCEEDED(afmf1->GetPerformanceMode(&perf)))
            out["performanceMode"] = static_cast<int>(perf);
        if (ADLX_SUCCEEDED(afmf1->GetFastMotionResponse(&fastMotion)))
            out["fastMotionResponse"] = static_cast<int>(fastMotion);
        adlx_bool algoSupported = false;
        if (ADLX_SUCCEEDED(afmf1->IsSupportedAlgorithm(&algoSupported)) && algoSupported)
        {
            ADLX_AFMF_ALGORITHM algo = {};
            if (ADLX_SUCCEEDED(afmf1->GetAlgorithm(&algo)))
                out["algorithm"] = static_cast<int>(algo);
        }
    }
    return out;
}

json GetTessellation(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DTessellationPtr tess;
    if (ADLX_FAILED(session.GfxServices()->GetTessellation(gpu, &tess)) || !tess)
        return {{"supported", false}};
    adlx_bool supported = false;
    tess->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    ADLX_TESSELLATION_MODE mode = {};
    ADLX_TESSELLATION_LEVEL level = {};
    tess->GetMode(&mode);
    tess->GetLevel(&level);
    return {{"supported", true}, {"mode", static_cast<int>(mode)}, {"level", static_cast<int>(level)}};
}

json GetAntiAliasing(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DAntiAliasingPtr aa;
    if (ADLX_FAILED(session.GfxServices()->GetAntiAliasing(gpu, &aa)) || !aa)
        return {{"supported", false}};
    adlx_bool supported = false;
    aa->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    ADLX_ANTI_ALIASING_MODE mode = {};
    ADLX_ANTI_ALIASING_LEVEL level = {};
    ADLX_ANTI_ALIASING_METHOD method = {};
    aa->GetMode(&mode);
    aa->GetLevel(&level);
    aa->GetMethod(&method);
    return {{"supported", true}, {"mode", static_cast<int>(mode)},
            {"level", static_cast<int>(level)}, {"method", static_cast<int>(method)}};
}

json GetMorphologicalAA(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DMorphologicalAntiAliasingPtr mlaa;
    if (ADLX_FAILED(session.GfxServices()->GetMorphologicalAntiAliasing(gpu, &mlaa)) || !mlaa)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    mlaa->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    mlaa->IsEnabled(&enabled);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
}

json GetAnisotropic(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DAnisotropicFilteringPtr af;
    if (ADLX_FAILED(session.GfxServices()->GetAnisotropicFiltering(gpu, &af)) || !af)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    af->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    af->IsEnabled(&enabled);
    ADLX_ANISOTROPIC_FILTERING_LEVEL level = {};
    af->GetLevel(&level);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)}, {"level", static_cast<int>(level)}};
}

json GetFsrUpgrade(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DSettingsServices3Ptr svc3 = session.GfxServices3();
    if (!svc3)
        return {{"supported", false}};
    IADLX3DFidelityFXSuperResolutionPtr fsr;
    if (ADLX_FAILED(svc3->GetFidelityFXSuperResolution(gpu, &fsr)) || !fsr)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    fsr->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    fsr->IsEnabled(&enabled);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
}

json GetFrameGenUpgrade(Session& session, IADLXGPUPtr& gpu)
{
    IADLX3DSettingsServices3Ptr svc3 = session.GfxServices3();
    if (!svc3)
        return {{"supported", false}};
    IADLX3DFidelityFXFrameGenUpgradePtr fg;
    if (ADLX_FAILED(svc3->GetFidelityFXFrameGenUpgrade(gpu, &fg)) || !fg)
        return {{"supported", false}};
    adlx_bool supported = false, enabled = false;
    fg->IsSupported(&supported);
    if (!supported)
        return {{"supported", false}};
    fg->IsEnabled(&enabled);
    ADLX_FFX_FRAME_GEN_RATIO ratio = FFX_FRAME_GEN_UNKNOWN;
    fg->GetRatio(&ratio);
    return {{"supported", true}, {"enabled", static_cast<bool>(enabled)}, {"ratio", static_cast<int>(ratio)}};
}

// ── gfx.get ──────────────────────────────────────────────────────────────────

json CmdGfxGet(Session& session, const json&)
{
    IADLXGPUPtr gpu = session.Gpu();
    return {
        {"antiLag", GetAntiLag(session, gpu)},
        {"chill", GetChill(session, gpu)},
        {"boost", GetBoost(session, gpu)},
        {"imageSharpening", GetImageSharpening(session, gpu)},
        {"imageSharpenDesktop", GetImageSharpenDesktop(session, gpu)},
        {"enhancedSync", GetEnhancedSync(session, gpu)},
        {"vsync", GetVSync(session, gpu)},
        {"frtc", GetFrtc(session, gpu)},
        {"rsr", GetRsr(session)},
        {"afmf", GetAfmf(session)},
        {"tessellation", GetTessellation(session, gpu)},
        {"antiAliasing", GetAntiAliasing(session, gpu)},
        {"morphologicalAA", GetMorphologicalAA(session, gpu)},
        {"anisotropicFiltering", GetAnisotropic(session, gpu)},
        {"fsrUpgrade", GetFsrUpgrade(session, gpu)},
        {"frameGenUpgrade", GetFrameGenUpgrade(session, gpu)},
    };
}

// ── gfx.set {"feature": "...", ...} ──────────────────────────────────────────

json CmdGfxSet(Session& session, const json& args)
{
    std::string feature = args.at("feature").get<std::string>();
    IADLXGPUPtr gpu = session.Gpu();

    if (feature == "antiLag")
    {
        IADLX3DAntiLagPtr al;
        Check(session.GfxServices()->GetAntiLag(gpu, &al), "GetAntiLag");
        if (args.contains("level"))
        {
            IADLX3DAntiLag1Ptr al1;
            if (ADLX_FAILED(al->QueryInterface(IADLX3DAntiLag1::IID(), reinterpret_cast<void**>(&al1))) || !al1)
                throw BridgeError("Anti-Lag level control not supported by this driver");
            Check(al1->SetLevel(static_cast<ADLX_ANTILAG_STATE>(args["level"].get<int>())), "AntiLag SetLevel");
        }
        if (args.contains("enabled"))
            Check(al->SetEnabled(args["enabled"].get<bool>()), "AntiLag SetEnabled");
    }
    else if (feature == "chill")
    {
        IADLX3DChillPtr chill;
        Check(session.GfxServices()->GetChill(gpu, &chill), "GetChill");
        // FPS bounds first so an enable lands with sane values already set.
        if (args.contains("minFps"))
            Check(chill->SetMinFPS(args["minFps"].get<adlx_int>()), "Chill SetMinFPS");
        if (args.contains("maxFps"))
            Check(chill->SetMaxFPS(args["maxFps"].get<adlx_int>()), "Chill SetMaxFPS");
        if (args.contains("enabled"))
            Check(chill->SetEnabled(args["enabled"].get<bool>()), "Chill SetEnabled");
    }
    else if (feature == "boost")
    {
        IADLX3DBoostPtr boost;
        Check(session.GfxServices()->GetBoost(gpu, &boost), "GetBoost");
        if (args.contains("minResolutionPct"))
            Check(boost->SetResolution(args["minResolutionPct"].get<adlx_int>()), "Boost SetResolution");
        if (args.contains("enabled"))
            Check(boost->SetEnabled(args["enabled"].get<bool>()), "Boost SetEnabled");
    }
    else if (feature == "imageSharpening")
    {
        IADLX3DImageSharpeningPtr ris;
        Check(session.GfxServices()->GetImageSharpening(gpu, &ris), "GetImageSharpening");
        if (args.contains("sharpness"))
            Check(ris->SetSharpness(args["sharpness"].get<adlx_int>()), "RIS SetSharpness");
        if (args.contains("enabled"))
            Check(ris->SetEnabled(args["enabled"].get<bool>()), "RIS SetEnabled");
    }
    else if (feature == "imageSharpenDesktop")
    {
        IADLX3DSettingsServices2Ptr svc2 = session.GfxServices2();
        if (!svc2)
            throw BridgeError("Desktop sharpening requires a newer driver (ADLX 2.1+)");
        IADLX3DImageSharpenDesktopPtr isd;
        Check(svc2->GetImageSharpenDesktop(gpu, &isd), "GetImageSharpenDesktop");
        Check(isd->SetEnabled(args.at("enabled").get<bool>()), "ImageSharpenDesktop SetEnabled");
    }
    else if (feature == "enhancedSync")
    {
        IADLX3DEnhancedSyncPtr es;
        Check(session.GfxServices()->GetEnhancedSync(gpu, &es), "GetEnhancedSync");
        Check(es->SetEnabled(args.at("enabled").get<bool>()), "EnhancedSync SetEnabled");
    }
    else if (feature == "vsync")
    {
        IADLX3DWaitForVerticalRefreshPtr vsync;
        Check(session.GfxServices()->GetWaitForVerticalRefresh(gpu, &vsync), "GetWaitForVerticalRefresh");
        Check(vsync->SetMode(static_cast<ADLX_WAIT_FOR_VERTICAL_REFRESH_MODE>(args.at("mode").get<int>())),
              "VSync SetMode");
    }
    else if (feature == "frtc")
    {
        IADLX3DFrameRateTargetControlPtr frtc;
        Check(session.GfxServices()->GetFrameRateTargetControl(gpu, &frtc), "GetFrameRateTargetControl");
        if (args.contains("fps"))
            Check(frtc->SetFPS(args["fps"].get<adlx_int>()), "FRTC SetFPS");
        if (args.contains("enabled"))
            Check(frtc->SetEnabled(args["enabled"].get<bool>()), "FRTC SetEnabled");
    }
    else if (feature == "rsr")
    {
        IADLX3DRadeonSuperResolutionPtr rsr;
        Check(session.GfxServices()->GetRadeonSuperResolution(&rsr), "GetRadeonSuperResolution");
        if (args.contains("sharpness"))
            Check(rsr->SetSharpness(args["sharpness"].get<adlx_int>()), "RSR SetSharpness");
        if (args.contains("enabled"))
            Check(rsr->SetEnabled(args["enabled"].get<bool>()), "RSR SetEnabled");
    }
    else if (feature == "afmf")
    {
        IADLX3DSettingsServices1Ptr svc1 = session.GfxServices1();
        if (!svc1)
            throw BridgeError("AFMF requires a newer driver (ADLX 1.4+)");
        IADLX3DAMDFluidMotionFramesPtr afmf;
        Check(svc1->GetAMDFluidMotionFrames(&afmf), "GetAMDFluidMotionFrames");

        IADLX3DAMDFluidMotionFrames1Ptr afmf1;
        afmf->QueryInterface(IADLX3DAMDFluidMotionFrames1::IID(), reinterpret_cast<void**>(&afmf1));
        if (args.contains("searchMode") || args.contains("performanceMode") ||
            args.contains("fastMotionResponse") || args.contains("algorithm"))
        {
            if (!afmf1)
                throw BridgeError("AFMF tuning options require a newer driver");
            if (args.contains("searchMode"))
                Check(afmf1->SetSearchMode(static_cast<ADLX_AFMF_SEARCH_MODE_TYPE>(args["searchMode"].get<int>())),
                      "AFMF SetSearchMode");
            if (args.contains("performanceMode"))
                Check(afmf1->SetPerformanceMode(static_cast<ADLX_AFMF_PERFORMANCE_MODE_TYPE>(args["performanceMode"].get<int>())),
                      "AFMF SetPerformanceMode");
            if (args.contains("fastMotionResponse"))
                Check(afmf1->SetFastMotionResponse(static_cast<ADLX_AFMF_FAST_MOTION_RESP>(args["fastMotionResponse"].get<int>())),
                      "AFMF SetFastMotionResponse");
            if (args.contains("algorithm"))
                Check(afmf1->SetAlgorithm(static_cast<ADLX_AFMF_ALGORITHM>(args["algorithm"].get<int>())),
                      "AFMF SetAlgorithm");
        }
        if (args.contains("enabled"))
            Check(afmf->SetEnabled(args["enabled"].get<bool>()), "AFMF SetEnabled");
    }
    else if (feature == "tessellation")
    {
        IADLX3DTessellationPtr tess;
        Check(session.GfxServices()->GetTessellation(gpu, &tess), "GetTessellation");
        if (args.contains("mode"))
            Check(tess->SetMode(static_cast<ADLX_TESSELLATION_MODE>(args["mode"].get<int>())), "Tessellation SetMode");
        if (args.contains("level"))
            Check(tess->SetLevel(static_cast<ADLX_TESSELLATION_LEVEL>(args["level"].get<int>())), "Tessellation SetLevel");
    }
    else if (feature == "antiAliasing")
    {
        IADLX3DAntiAliasingPtr aa;
        Check(session.GfxServices()->GetAntiAliasing(gpu, &aa), "GetAntiAliasing");
        if (args.contains("mode"))
            Check(aa->SetMode(static_cast<ADLX_ANTI_ALIASING_MODE>(args["mode"].get<int>())), "AA SetMode");
        if (args.contains("level"))
            Check(aa->SetLevel(static_cast<ADLX_ANTI_ALIASING_LEVEL>(args["level"].get<int>())), "AA SetLevel");
        if (args.contains("method"))
            Check(aa->SetMethod(static_cast<ADLX_ANTI_ALIASING_METHOD>(args["method"].get<int>())), "AA SetMethod");
    }
    else if (feature == "morphologicalAA")
    {
        IADLX3DMorphologicalAntiAliasingPtr mlaa;
        Check(session.GfxServices()->GetMorphologicalAntiAliasing(gpu, &mlaa), "GetMorphologicalAntiAliasing");
        Check(mlaa->SetEnabled(args.at("enabled").get<bool>()), "MLAA SetEnabled");
    }
    else if (feature == "anisotropicFiltering")
    {
        IADLX3DAnisotropicFilteringPtr af;
        Check(session.GfxServices()->GetAnisotropicFiltering(gpu, &af), "GetAnisotropicFiltering");
        if (args.contains("level"))
            Check(af->SetLevel(static_cast<ADLX_ANISOTROPIC_FILTERING_LEVEL>(args["level"].get<int>())), "AF SetLevel");
        if (args.contains("enabled"))
            Check(af->SetEnabled(args["enabled"].get<bool>()), "AF SetEnabled");
    }
    else if (feature == "fsrUpgrade")
    {
        IADLX3DSettingsServices3Ptr svc3 = session.GfxServices3();
        if (!svc3)
            throw BridgeError("FSR upgrade requires a newer driver (ADLX 3.1+)");
        IADLX3DFidelityFXSuperResolutionPtr fsr;
        Check(svc3->GetFidelityFXSuperResolution(gpu, &fsr), "GetFidelityFXSuperResolution");
        Check(fsr->SetEnabled(args.at("enabled").get<bool>()), "FSR upgrade SetEnabled");
    }
    else if (feature == "frameGenUpgrade")
    {
        IADLX3DSettingsServices3Ptr svc3 = session.GfxServices3();
        if (!svc3)
            throw BridgeError("Frame-gen upgrade requires a newer driver (ADLX 3.1+)");
        IADLX3DFidelityFXFrameGenUpgradePtr fg;
        Check(svc3->GetFidelityFXFrameGenUpgrade(gpu, &fg), "GetFidelityFXFrameGenUpgrade");
        if (args.contains("ratio"))
            Check(fg->SetRatio(static_cast<ADLX_FFX_FRAME_GEN_RATIO>(args["ratio"].get<int>())), "FrameGen SetRatio");
        if (args.contains("enabled"))
            Check(fg->SetEnabled(args["enabled"].get<bool>()), "FrameGen SetEnabled");
    }
    else
    {
        throw BridgeError("Unknown gfx feature: " + feature);
    }

    return {{"feature", feature}, {"applied", true}};
}

// ── gfx.resetShaderCache ─────────────────────────────────────────────────────

json CmdResetShaderCache(Session& session, const json&)
{
    IADLXGPUPtr gpu = session.Gpu();
    IADLX3DResetShaderCachePtr rsc;
    Check(session.GfxServices()->GetResetShaderCache(gpu, &rsc), "GetResetShaderCache");
    adlx_bool supported = false;
    rsc->IsSupported(&supported);
    if (!supported)
        throw BridgeError("Shader cache reset not supported on this GPU");
    Check(rsc->ResetShaderCache(), "ResetShaderCache");
    return {{"reset", true}};
}

}  // namespace

void RegisterGfx(Registry& reg)
{
    reg["gfx.get"] = CmdGfxGet;
    reg["gfx.set"] = CmdGfxSet;
    reg["gfx.resetShaderCache"] = CmdResetShaderCache;
}

}  // namespace voltshift
