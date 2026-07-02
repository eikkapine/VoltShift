// VoltShift bridge — per-display settings.
//
// Displays are addressed by their list index as reported by display.list;
// the uniqueId in that listing lets the client detect topology changes.
#include "rpc.h"

using namespace adlx;

namespace voltshift {

namespace {

IADLXDisplayPtr DisplayByIndex(Session& session, adlx_uint index)
{
    IADLXDisplayListPtr list;
    Check(session.DisplayServices()->GetDisplays(&list), "GetDisplays");
    adlx_uint count = list->End() - list->Begin();
    if (index >= count)
        throw BridgeError("Display index out of range (have " + std::to_string(count) + " displays)");
    IADLXDisplayPtr display;
    Check(list->At(list->Begin() + index, &display), "DisplayList::At");
    return display;
}

json RangeJson(const ADLX_IntRange& r)
{
    return {{"min", r.minValue}, {"max", r.maxValue}, {"step", r.step}};
}

// ── display.list ─────────────────────────────────────────────────────────────

json CmdDisplayList(Session& session, const json&)
{
    IADLXDisplayListPtr list;
    Check(session.DisplayServices()->GetDisplays(&list), "GetDisplays");

    json displays = json::array();
    for (adlx_uint i = list->Begin(); i != list->End(); ++i)
    {
        IADLXDisplayPtr display;
        if (ADLX_FAILED(list->At(i, &display)))
            continue;

        const char* name = nullptr;
        display->Name(&name);
        adlx_size uniqueId = 0;
        display->UniqueId(&uniqueId);
        adlx_int width = 0, height = 0;
        display->NativeResolution(&width, &height);
        adlx_double refresh = 0;
        display->RefreshRate(&refresh);
        ADLX_DISPLAY_CONNECTOR_TYPE connector = {};
        display->ConnectorType(&connector);
        ADLX_DISPLAY_TYPE type = {};
        display->DisplayType(&type);

        displays.push_back({
            {"index", i - list->Begin()},
            {"name", name ? name : "unknown"},
            {"uniqueId", static_cast<uint64_t>(uniqueId)},
            {"width", width},
            {"height", height},
            {"refreshHz", refresh},
            {"connector", static_cast<int>(connector)},
            {"type", static_cast<int>(type)},
        });
    }
    return {{"displays", displays}};
}

// ── display.get {"index": 0} ─────────────────────────────────────────────────

json CmdDisplayGet(Session& session, const json& args)
{
    adlx_uint index = args.value("index", 0u);
    IADLXDisplayPtr display = DisplayByIndex(session, index);
    IADLXDisplayServicesPtr svc = session.DisplayServices();

    json out = {{"index", index}};

    {
        IADLXDisplayFreeSyncPtr freeSync;
        json fj = {{"supported", false}};
        if (ADLX_SUCCEEDED(svc->GetFreeSync(display, &freeSync)) && freeSync)
        {
            adlx_bool supported = false, enabled = false;
            freeSync->IsSupported(&supported);
            if (supported)
            {
                freeSync->IsEnabled(&enabled);
                fj = {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
            }
        }
        out["freeSync"] = fj;
    }
    {
        IADLXDisplayVSRPtr vsr;
        json vj = {{"supported", false}};
        if (ADLX_SUCCEEDED(svc->GetVirtualSuperResolution(display, &vsr)) && vsr)
        {
            adlx_bool supported = false, enabled = false;
            vsr->IsSupported(&supported);
            if (supported)
            {
                vsr->IsEnabled(&enabled);
                vj = {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
            }
        }
        out["vsr"] = vj;
    }
    {
        IADLXDisplayGPUScalingPtr scaling;
        json sj = {{"supported", false}};
        if (ADLX_SUCCEEDED(svc->GetGPUScaling(display, &scaling)) && scaling)
        {
            adlx_bool supported = false, enabled = false;
            scaling->IsSupported(&supported);
            if (supported)
            {
                scaling->IsEnabled(&enabled);
                sj = {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
            }
        }
        out["gpuScaling"] = sj;
    }
    {
        IADLXDisplayScalingModePtr mode;
        json mj = {{"supported", false}};
        if (ADLX_SUCCEEDED(svc->GetScalingMode(display, &mode)) && mode)
        {
            adlx_bool supported = false;
            mode->IsSupported(&supported);
            if (supported)
            {
                ADLX_SCALE_MODE current = {};
                mode->GetMode(&current);
                // 0=preserve aspect, 1=full panel, 2=centered
                mj = {{"supported", true}, {"mode", static_cast<int>(current)}};
            }
        }
        out["scalingMode"] = mj;
    }
    {
        IADLXDisplayIntegerScalingPtr integer;
        json ij = {{"supported", false}};
        if (ADLX_SUCCEEDED(svc->GetIntegerScaling(display, &integer)) && integer)
        {
            adlx_bool supported = false, enabled = false;
            integer->IsSupported(&supported);
            if (supported)
            {
                integer->IsEnabled(&enabled);
                ij = {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
            }
        }
        out["integerScaling"] = ij;
    }
    {
        IADLXDisplayColorDepthPtr depth;
        json dj = {{"supported", false}};
        if (ADLX_SUCCEEDED(svc->GetColorDepth(display, &depth)) && depth)
        {
            adlx_bool supported = false;
            depth->IsSupported(&supported);
            if (supported)
            {
                ADLX_COLOR_DEPTH current = {};
                depth->GetValue(&current);
                json options = json::array();
                struct { ADLX_COLOR_DEPTH value; ADLX_RESULT (ADLX_STD_CALL IADLXDisplayColorDepth::*probe)(adlx_bool*); } probes[] = {
                    {BPC_6, &IADLXDisplayColorDepth::IsSupportedBPC_6},
                    {BPC_8, &IADLXDisplayColorDepth::IsSupportedBPC_8},
                    {BPC_10, &IADLXDisplayColorDepth::IsSupportedBPC_10},
                    {BPC_12, &IADLXDisplayColorDepth::IsSupportedBPC_12},
                    {BPC_14, &IADLXDisplayColorDepth::IsSupportedBPC_14},
                    {BPC_16, &IADLXDisplayColorDepth::IsSupportedBPC_16},
                };
                for (auto& p : probes)
                {
                    adlx_bool ok = false;
                    if (ADLX_SUCCEEDED((depth.GetPtr()->*p.probe)(&ok)) && ok)
                        options.push_back(static_cast<int>(p.value));
                }
                dj = {{"supported", true}, {"value", static_cast<int>(current)}, {"options", options}};
            }
        }
        out["colorDepth"] = dj;
    }
    {
        IADLXDisplayPixelFormatPtr format;
        json pj = {{"supported", false}};
        if (ADLX_SUCCEEDED(svc->GetPixelFormat(display, &format)) && format)
        {
            adlx_bool supported = false;
            format->IsSupported(&supported);
            if (supported)
            {
                ADLX_PIXEL_FORMAT current = {};
                format->GetValue(&current);
                json options = json::array();
                struct { ADLX_PIXEL_FORMAT value; ADLX_RESULT (ADLX_STD_CALL IADLXDisplayPixelFormat::*probe)(adlx_bool*); } probes[] = {
                    {RGB_444_FULL, &IADLXDisplayPixelFormat::IsSupportedRGB444Full},
                    {YCBCR_444, &IADLXDisplayPixelFormat::IsSupportedYCbCr444},
                    {YCBCR_422, &IADLXDisplayPixelFormat::IsSupportedYCbCr422},
                    {RGB_444_LIMITED, &IADLXDisplayPixelFormat::IsSupportedRGB444Limited},
                    {YCBCR_420, &IADLXDisplayPixelFormat::IsSupportedYCbCr420},
                };
                for (auto& p : probes)
                {
                    adlx_bool ok = false;
                    if (ADLX_SUCCEEDED((format.GetPtr()->*p.probe)(&ok)) && ok)
                        options.push_back(static_cast<int>(p.value));
                }
                pj = {{"supported", true}, {"value", static_cast<int>(current)}, {"options", options}};
            }
        }
        out["pixelFormat"] = pj;
    }
    {
        IADLXDisplayCustomColorPtr color;
        json cj = json::object();
        if (ADLX_SUCCEEDED(svc->GetCustomColor(display, &color)) && color)
        {
            struct Channel {
                const char* key;
                ADLX_RESULT (ADLX_STD_CALL IADLXDisplayCustomColor::*isSupported)(adlx_bool*);
                ADLX_RESULT (ADLX_STD_CALL IADLXDisplayCustomColor::*getRange)(ADLX_IntRange*);
                ADLX_RESULT (ADLX_STD_CALL IADLXDisplayCustomColor::*get)(adlx_int*);
            };
            Channel channels[] = {
                {"brightness", &IADLXDisplayCustomColor::IsBrightnessSupported,
                 &IADLXDisplayCustomColor::GetBrightnessRange, &IADLXDisplayCustomColor::GetBrightness},
                {"contrast", &IADLXDisplayCustomColor::IsContrastSupported,
                 &IADLXDisplayCustomColor::GetContrastRange, &IADLXDisplayCustomColor::GetContrast},
                {"saturation", &IADLXDisplayCustomColor::IsSaturationSupported,
                 &IADLXDisplayCustomColor::GetSaturationRange, &IADLXDisplayCustomColor::GetSaturation},
                {"hue", &IADLXDisplayCustomColor::IsHueSupported,
                 &IADLXDisplayCustomColor::GetHueRange, &IADLXDisplayCustomColor::GetHue},
                {"temperature", &IADLXDisplayCustomColor::IsTemperatureSupported,
                 &IADLXDisplayCustomColor::GetTemperatureRange, &IADLXDisplayCustomColor::GetTemperature},
            };
            for (auto& ch : channels)
            {
                adlx_bool supported = false;
                if (ADLX_SUCCEEDED((color.GetPtr()->*ch.isSupported)(&supported)) && supported)
                {
                    adlx_int value = 0;
                    ADLX_IntRange range = {};
                    (color.GetPtr()->*ch.get)(&value);
                    (color.GetPtr()->*ch.getRange)(&range);
                    cj[ch.key] = {{"supported", true}, {"value", value}, {"range", RangeJson(range)}};
                }
                else
                {
                    cj[ch.key] = {{"supported", false}};
                }
            }
        }
        out["customColor"] = cj;
    }
    {
        IADLXDisplayVariBrightPtr vb;
        json vj = {{"supported", false}};
        if (ADLX_SUCCEEDED(svc->GetVariBright(display, &vb)) && vb)
        {
            adlx_bool supported = false, enabled = false;
            vb->IsSupported(&supported);
            if (supported)
            {
                vb->IsEnabled(&enabled);
                vj = {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
            }
        }
        out["variBright"] = vj;
    }
    {
        IADLXDisplayHDCPPtr hdcp;
        json hj = {{"supported", false}};
        if (ADLX_SUCCEEDED(svc->GetHDCP(display, &hdcp)) && hdcp)
        {
            adlx_bool supported = false, enabled = false;
            hdcp->IsSupported(&supported);
            if (supported)
            {
                hdcp->IsEnabled(&enabled);
                hj = {{"supported", true}, {"enabled", static_cast<bool>(enabled)}};
            }
        }
        out["hdcp"] = hj;
    }

    return out;
}

// ── display.set {"index":0,"feature":"freeSync","enabled":true,...} ──────────

json CmdDisplaySet(Session& session, const json& args)
{
    adlx_uint index = args.value("index", 0u);
    std::string feature = args.at("feature").get<std::string>();
    IADLXDisplayPtr display = DisplayByIndex(session, index);
    IADLXDisplayServicesPtr svc = session.DisplayServices();

    if (feature == "freeSync")
    {
        IADLXDisplayFreeSyncPtr freeSync;
        Check(svc->GetFreeSync(display, &freeSync), "GetFreeSync");
        Check(freeSync->SetEnabled(args.at("enabled").get<bool>()), "FreeSync SetEnabled");
    }
    else if (feature == "vsr")
    {
        IADLXDisplayVSRPtr vsr;
        Check(svc->GetVirtualSuperResolution(display, &vsr), "GetVirtualSuperResolution");
        Check(vsr->SetEnabled(args.at("enabled").get<bool>()), "VSR SetEnabled");
    }
    else if (feature == "gpuScaling")
    {
        IADLXDisplayGPUScalingPtr scaling;
        Check(svc->GetGPUScaling(display, &scaling), "GetGPUScaling");
        Check(scaling->SetEnabled(args.at("enabled").get<bool>()), "GPUScaling SetEnabled");
    }
    else if (feature == "scalingMode")
    {
        IADLXDisplayScalingModePtr mode;
        Check(svc->GetScalingMode(display, &mode), "GetScalingMode");
        Check(mode->SetMode(static_cast<ADLX_SCALE_MODE>(args.at("mode").get<int>())), "ScalingMode SetMode");
    }
    else if (feature == "integerScaling")
    {
        IADLXDisplayIntegerScalingPtr integer;
        Check(svc->GetIntegerScaling(display, &integer), "GetIntegerScaling");
        Check(integer->SetEnabled(args.at("enabled").get<bool>()), "IntegerScaling SetEnabled");
    }
    else if (feature == "colorDepth")
    {
        IADLXDisplayColorDepthPtr depth;
        Check(svc->GetColorDepth(display, &depth), "GetColorDepth");
        Check(depth->SetValue(static_cast<ADLX_COLOR_DEPTH>(args.at("value").get<int>())), "ColorDepth SetValue");
    }
    else if (feature == "pixelFormat")
    {
        IADLXDisplayPixelFormatPtr format;
        Check(svc->GetPixelFormat(display, &format), "GetPixelFormat");
        Check(format->SetValue(static_cast<ADLX_PIXEL_FORMAT>(args.at("value").get<int>())), "PixelFormat SetValue");
    }
    else if (feature == "customColor")
    {
        IADLXDisplayCustomColorPtr color;
        Check(svc->GetCustomColor(display, &color), "GetCustomColor");
        if (args.contains("brightness"))
            Check(color->SetBrightness(args["brightness"].get<adlx_int>()), "SetBrightness");
        if (args.contains("contrast"))
            Check(color->SetContrast(args["contrast"].get<adlx_int>()), "SetContrast");
        if (args.contains("saturation"))
            Check(color->SetSaturation(args["saturation"].get<adlx_int>()), "SetSaturation");
        if (args.contains("hue"))
            Check(color->SetHue(args["hue"].get<adlx_int>()), "SetHue");
        if (args.contains("temperature"))
            Check(color->SetTemperature(args["temperature"].get<adlx_int>()), "SetTemperature");
    }
    else if (feature == "variBright")
    {
        IADLXDisplayVariBrightPtr vb;
        Check(svc->GetVariBright(display, &vb), "GetVariBright");
        Check(vb->SetEnabled(args.at("enabled").get<bool>()), "VariBright SetEnabled");
    }
    else if (feature == "hdcp")
    {
        IADLXDisplayHDCPPtr hdcp;
        Check(svc->GetHDCP(display, &hdcp), "GetHDCP");
        Check(hdcp->SetEnabled(args.at("enabled").get<bool>()), "HDCP SetEnabled");
    }
    else
    {
        throw BridgeError("Unknown display feature: " + feature);
    }

    return {{"index", index}, {"feature", feature}, {"applied", true}};
}

}  // namespace

void RegisterDisplay(Registry& reg)
{
    reg["display.list"] = CmdDisplayList;
    reg["display.get"] = CmdDisplayGet;
    reg["display.set"] = CmdDisplaySet;
}

}  // namespace voltshift
