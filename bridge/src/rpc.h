// VoltShift bridge — command registry.
//
// Handlers receive parsed args and return the "data" payload; the REPL in
// main.cpp wraps it in the response envelope. Handlers signal failure by
// throwing BridgeError (or any std::exception).
#pragma once

#include <functional>
#include <map>
#include <string>

#include <nlohmann/json.hpp>

#include "session.h"

namespace voltshift {

using json = nlohmann::json;
using Handler = std::function<json(Session&, const json& args)>;
using Registry = std::map<std::string, Handler>;

void RegisterCore(Registry& reg);      // ping, info, caps, metrics
void RegisterTuning(Registry& reg);    // tuning.*
void RegisterGfx(Registry& reg);       // gfx.*
void RegisterDisplay(Registry& reg);   // display.*
void RegisterExtras(Registry& reg);    // media.*, desktop.*

}  // namespace voltshift
