// VoltShift bridge — multimedia (video processing) and desktop (Eyefinity).
#include "rpc.h"

using namespace adlx;

namespace voltshift {

namespace {

// ── media.get ────────────────────────────────────────────────────────────────

json CmdMediaGet(Session& session, const json&)
{
    IADLXMultimediaServicesPtr svc = session.MultimediaServices();
    if (!svc)
        return {{"videoUpscale", {{"supported", false}}},
                {"videoSuperResolution", {{"supported", false}}},
                {"note", "Multimedia services require a newer driver (ADLX 3.0+)"}};

    IADLXGPUPtr gpu = session.Gpu();
    json out = json::object();

    {
        json uj = {{"supported", false}};
        IADLXVideoUpscalePtr upscale;
        if (ADLX_SUCCEEDED(svc->GetVideoUpscale(gpu, &upscale)) && upscale)
        {
            adlx_bool supported = false, enabled = false;
            upscale->IsSupported(&supported);
            if (supported)
            {
                upscale->IsEnabled(&enabled);
                adlx_int sharpness = 0;
                ADLX_IntRange range = {};
                upscale->GetSharpness(&sharpness);
                upscale->GetSharpnessRange(&range);
                uj = {{"supported", true}, {"enabled", static_cast<bool>(enabled)},
                      {"sharpness", sharpness},
                      {"sharpnessRange", {{"min", range.minValue}, {"max", range.maxValue}, {"step", range.step}}}};
            }
        }
        out["videoUpscale"] = uj;
    }
    {
        json vj = {{"supported", false}};
        IADLXVideoSuperResolutionPtr vsr;
        if (ADLX_SUCCEEDED(svc->GetVideoSuperResolution(gpu, &vsr)) && vsr)
        {
            adlx_bool supported = false, enabled = false;
            vsr->IsSupported(&supported);
            if (supported)
            {
                vsr->IsEnabled(&enabled);
                vj = {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
            }
        }
        out["videoSuperResolution"] = vj;
    }

    return out;
}

// ── media.set {"feature":"videoUpscale","enabled":true,"sharpness":50} ───────

json CmdMediaSet(Session& session, const json& args)
{
    IADLXMultimediaServicesPtr svc = session.MultimediaServices();
    if (!svc)
        throw BridgeError("Multimedia services require a newer driver (ADLX 3.0+)");

    std::string feature = args.at("feature").get<std::string>();
    IADLXGPUPtr gpu = session.Gpu();

    if (feature == "videoUpscale")
    {
        IADLXVideoUpscalePtr upscale;
        Check(svc->GetVideoUpscale(gpu, &upscale), "GetVideoUpscale");
        if (args.contains("sharpness"))
            Check(upscale->SetSharpness(args["sharpness"].get<adlx_int>()), "VideoUpscale SetSharpness");
        if (args.contains("enabled"))
            Check(upscale->SetEnabled(args["enabled"].get<bool>()), "VideoUpscale SetEnabled");
    }
    else if (feature == "videoSuperResolution")
    {
        IADLXVideoSuperResolutionPtr vsr;
        Check(svc->GetVideoSuperResolution(gpu, &vsr), "GetVideoSuperResolution");
        Check(vsr->SetEnabled(args.at("enabled").get<bool>()), "VideoSuperResolution SetEnabled");
    }
    else
    {
        throw BridgeError("Unknown media feature: " + feature);
    }

    return {{"feature", feature}, {"applied", true}};
}

// ── desktop.list ─────────────────────────────────────────────────────────────

json CmdDesktopList(Session& session, const json&)
{
    IADLXDesktopListPtr list;
    Check(session.DesktopServices()->GetDesktops(&list), "GetDesktops");

    json desktops = json::array();
    for (adlx_uint i = list->Begin(); i != list->End(); ++i)
    {
        IADLXDesktopPtr desktop;
        if (ADLX_FAILED(list->At(i, &desktop)))
            continue;

        adlx_int width = 0, height = 0;
        desktop->Size(&width, &height);
        ADLX_DESKTOP_TYPE type = {};
        desktop->Type(&type);
        adlx_uint numDisplays = 0;
        desktop->GetNumberOfDisplays(&numDisplays);

        desktops.push_back({
            {"index", i - list->Begin()},
            {"width", width},
            {"height", height},
            {"type", static_cast<int>(type)},  // 0=single, 1=duplicate, 2=eyefinity
            {"displayCount", numDisplays},
        });
    }
    return {{"desktops", desktops}};
}

// ── desktop.eyefinity {"action":"status"|"create"|"destroyAll"} ──────────────

json CmdEyefinity(Session& session, const json& args)
{
    IADLXSimpleEyefinityPtr eyefinity;
    Check(session.DesktopServices()->GetSimpleEyefinity(&eyefinity), "GetSimpleEyefinity");

    std::string action = args.value("action", "status");
    if (action == "status")
    {
        adlx_bool supported = false;
        eyefinity->IsSupported(&supported);
        return {{"supported", static_cast<bool>(supported)}};
    }
    if (action == "create")
    {
        IADLXEyefinityDesktopPtr desktop;
        Check(eyefinity->Create(&desktop), "Eyefinity Create");
        adlx_uint rows = 0, cols = 0;
        desktop->GridSize(&rows, &cols);
        return {{"created", true}, {"rows", rows}, {"cols", cols}};
    }
    if (action == "destroyAll")
    {
        Check(eyefinity->DestroyAll(), "Eyefinity DestroyAll");
        return {{"destroyed", true}};
    }
    throw BridgeError("Unknown eyefinity action: " + action + " (use status/create/destroyAll)");
}

}  // namespace

void RegisterExtras(Registry& reg)
{
    reg["media.get"] = CmdMediaGet;
    reg["media.set"] = CmdMediaSet;
    reg["desktop.list"] = CmdDesktopList;
    reg["desktop.eyefinity"] = CmdEyefinity;
}

}  // namespace voltshift
