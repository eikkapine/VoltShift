// VoltShift bridge — core commands: ping, info, caps, metrics.
#include "rpc.h"

#include "SDK/Include/IGPUManualGFXTuning.h"

using namespace adlx;

namespace voltshift {

namespace {

json CmdPing(Session&, const json&)
{
    return {{"pong", true}};
}

json CmdInfo(Session& session, const json&)
{
    IADLXGPUPtr gpu = session.Gpu();

    const char* name = nullptr;
    const char* vendorId = nullptr;
    const char* deviceId = nullptr;
    const char* revisionId = nullptr;
    const char* vramType = nullptr;
    const char* driverPath = nullptr;
    adlx_uint vramMB = 0;
    adlx_int uniqueId = 0;
    ADLX_ASIC_FAMILY_TYPE asicFamily = ASIC_UNDEFINED;

    gpu->Name(&name);
    gpu->VendorId(&vendorId);
    gpu->DeviceId(&deviceId);
    gpu->RevisionId(&revisionId);
    gpu->VRAMType(&vramType);
    gpu->DriverPath(&driverPath);
    gpu->TotalVRAM(&vramMB);
    gpu->UniqueId(&uniqueId);
    gpu->ASICFamilyType(&asicFamily);

    const char* biosPart = nullptr;
    const char* biosVersion = nullptr;
    const char* biosDate = nullptr;
    gpu->BIOSInfo(&biosPart, &biosVersion, &biosDate);

    return {
        {"name", name ? name : "unknown"},
        {"vendorId", vendorId ? vendorId : ""},
        {"deviceId", deviceId ? deviceId : ""},
        {"revisionId", revisionId ? revisionId : ""},
        {"vramType", vramType ? vramType : ""},
        {"vramMb", vramMB},
        {"uniqueId", uniqueId},
        {"asicFamily", static_cast<int>(asicFamily)},
        {"driverPath", driverPath ? driverPath : ""},
        {"bios", {{"partNumber", biosPart ? biosPart : ""},
                  {"version", biosVersion ? biosVersion : ""},
                  {"date", biosDate ? biosDate : ""}}},
    };
}

// Which tuning interface generation the GPU exposes for manual GFX tuning.
json GfxTuningInterface(Session& session, IADLXGPUPtr& gpu, IADLXGPUTuningServicesPtr& svc)
{
    json out = {{"mgt1", false}, {"mgt2", false}, {"mgt2_1", false}};

    adlx_bool supported = false;
    svc->IsSupportedManualGFXTuning(gpu, &supported);
    if (!supported)
        return out;

    IADLXInterfacePtr ifc;
    if (ADLX_FAILED(svc->GetManualGFXTuning(gpu, &ifc)) || !ifc)
        return out;

    IADLXManualGraphicsTuning1Ptr mgt1;
    IADLXManualGraphicsTuning2Ptr mgt2;
    IADLXManualGraphicsTuning2_1Ptr mgt21;
    out["mgt1"] = ADLX_SUCCEEDED(ifc->QueryInterface(IADLXManualGraphicsTuning1::IID(), reinterpret_cast<void**>(&mgt1)));
    out["mgt2"] = ADLX_SUCCEEDED(ifc->QueryInterface(IADLXManualGraphicsTuning2::IID(), reinterpret_cast<void**>(&mgt2)));
    out["mgt2_1"] = ADLX_SUCCEEDED(ifc->QueryInterface(IADLXManualGraphicsTuning2_1::IID(), reinterpret_cast<void**>(&mgt21)));
    return out;
}

json CmdCaps(Session& session, const json&)
{
    IADLXGPUPtr gpu = session.Gpu();
    IADLXGPUTuningServicesPtr tuningSvc = session.TuningServices();

    adlx_bool autoTuning = false, presetTuning = false;
    adlx_bool manualGfx = false, manualVram = false, manualFan = false, manualPower = false;
    adlx_bool atFactory = false;
    tuningSvc->IsSupportedAutoTuning(gpu, &autoTuning);
    tuningSvc->IsSupportedPresetTuning(gpu, &presetTuning);
    tuningSvc->IsSupportedManualGFXTuning(gpu, &manualGfx);
    tuningSvc->IsSupportedManualVRAMTuning(gpu, &manualVram);
    tuningSvc->IsSupportedManualFanTuning(gpu, &manualFan);
    tuningSvc->IsSupportedManualPowerTuning(gpu, &manualPower);
    tuningSvc->IsAtFactory(gpu, &atFactory);

    adlx_uint displayCount = 0;
    session.DisplayServices()->GetNumberOfDisplays(&displayCount);

    adlx_bool eyefinity = false;
    {
        IADLXSimpleEyefinityPtr ef;
        if (ADLX_SUCCEEDED(session.DesktopServices()->GetSimpleEyefinity(&ef)) && ef)
            ef->IsSupported(&eyefinity);
    }

    return {
        {"tuning", {
            {"autoTuning", static_cast<bool>(autoTuning)},
            {"presetTuning", static_cast<bool>(presetTuning)},
            {"manualGfx", static_cast<bool>(manualGfx)},
            {"manualVram", static_cast<bool>(manualVram)},
            {"manualFan", static_cast<bool>(manualFan)},
            {"manualPower", static_cast<bool>(manualPower)},
            {"atFactory", static_cast<bool>(atFactory)},
            {"gfxInterface", GfxTuningInterface(session, gpu, tuningSvc)},
        }},
        {"displayCount", displayCount},
        {"eyefinity", static_cast<bool>(eyefinity)},
        {"multimedia", session.MultimediaServices() != nullptr},
        {"gfx2", session.GfxServices2() != nullptr},
        {"gfx3", session.GfxServices3() != nullptr},
    };
}

json CmdMetrics(Session& session, const json&)
{
    IADLXGPUPtr gpu = session.Gpu();
    IADLXPerformanceMonitoringServicesPtr perf = session.PerfServices();

    IADLXGPUMetricsSupportPtr support;
    Check(perf->GetSupportedGPUMetrics(gpu, &support), "GetSupportedGPUMetrics");
    IADLXGPUMetricsPtr metrics;
    Check(perf->GetCurrentGPUMetrics(gpu, &metrics), "GetCurrentGPUMetrics");

    json out = json::object();

    adlx_int64 ts = 0;
    if (ADLX_SUCCEEDED(metrics->TimeStamp(&ts)))
        out["timestampMs"] = ts;

    adlx_bool ok = false;

    // Each metric: only reported when the driver says it's supported AND the
    // read succeeds, so the client can distinguish "0" from "unavailable".
    if (ADLX_SUCCEEDED(support->IsSupportedGPUClockSpeed(&ok)) && ok) {
        adlx_int v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUClockSpeed(&v))) out["clockMhz"] = v;
    }
    if (ADLX_SUCCEEDED(support->IsSupportedGPUVRAMClockSpeed(&ok)) && ok) {
        adlx_int v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUVRAMClockSpeed(&v))) out["vramClockMhz"] = v;
    }
    if (ADLX_SUCCEEDED(support->IsSupportedGPUTemperature(&ok)) && ok) {
        adlx_double v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUTemperature(&v))) out["tempC"] = v;
    }
    if (ADLX_SUCCEEDED(support->IsSupportedGPUHotspotTemperature(&ok)) && ok) {
        adlx_double v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUHotspotTemperature(&v))) out["hotspotC"] = v;
    }
    if (ADLX_SUCCEEDED(support->IsSupportedGPUIntakeTemperature(&ok)) && ok) {
        adlx_double v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUIntakeTemperature(&v))) out["intakeC"] = v;
    }
    if (ADLX_SUCCEEDED(support->IsSupportedGPUPower(&ok)) && ok) {
        adlx_double v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUPower(&v))) out["powerW"] = v;
    }
    if (ADLX_SUCCEEDED(support->IsSupportedGPUTotalBoardPower(&ok)) && ok) {
        adlx_double v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUTotalBoardPower(&v))) out["boardPowerW"] = v;
    }
    if (ADLX_SUCCEEDED(support->IsSupportedGPUFanSpeed(&ok)) && ok) {
        adlx_int v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUFanSpeed(&v))) out["fanRpm"] = v;
    }
    if (ADLX_SUCCEEDED(support->IsSupportedGPUVRAM(&ok)) && ok) {
        adlx_int v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUVRAM(&v))) out["vramUsedMb"] = v;
    }
    if (ADLX_SUCCEEDED(support->IsSupportedGPUVoltage(&ok)) && ok) {
        adlx_int v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUVoltage(&v))) out["voltageMv"] = v;
    }
    if (ADLX_SUCCEEDED(support->IsSupportedGPUUsage(&ok)) && ok) {
        adlx_double v = 0;
        if (ADLX_SUCCEEDED(metrics->GPUUsage(&v))) out["usagePct"] = v;
    }

    return out;
}

}  // namespace

void RegisterCore(Registry& reg)
{
    reg["ping"] = CmdPing;
    reg["info"] = CmdInfo;
    reg["caps"] = CmdCaps;
    reg["metrics"] = CmdMetrics;
}

}  // namespace voltshift
