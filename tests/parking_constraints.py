#!/usr/bin/env python3
"""Client minimum sizes while parking narrow tiled windows, then restoring them."""
import json
import os
import time

from desktop_test import desktop_test
from live import command, configure, h, wait
from native_session import NativeSession
from stash import SPECIAL


@desktop_test("Minimum-constrained tiled window parking")
def main():
    with NativeSession() as session:
        configure("presentation", "dock")
        configure("hoverPreview", "off")
        configure("animations", "off")
        original_monitor, original_workspace = session.monitor, session.workspace
        existing = {monitor["name"] for monitor in h.read("monitors")}
        rule_key = "__window_stash_parking_constraints_"+str(os.getpid())
        h.eval("_G."+rule_key+"={}")
        try:
            h.call("output", "create", "headless")
            monitor = wait(lambda: next((m for m in h.read("monitors") if m["name"] not in existing), None),
                           "Constraint test output did not appear")
            session.outputs.append(monitor["name"])
            end = max(m["x"]+round(m["width"]/m["scale"]) for m in h.read("monitors") if m["name"] in existing)
            h.eval("hl.monitor({output="+json.dumps(monitor["name"])
                   +",mode=\"320x240@60\",position="+json.dumps(str(end)+"x0")+",scale=1})")
            session.monitor = next(m for m in h.read("monitors") if m["name"] == monitor["name"])
            for index, layout in enumerate(("dwindle", "scrolling"), 1):
                session.workspace = original_workspace+index
                h.eval("table.insert(_G."+rule_key+",hl.workspace_rule({workspace="
                       +json.dumps(str(session.workspace))+",layout="+json.dumps(layout)+"}))")
                h.dispatch("focus", monitor=session.monitor["name"])
                h.dispatch("focus", workspace=str(session.workspace))
                address, _ = session.spawn(workspace=session.workspace)
                if layout == "scrolling":
                    h.dispatch("focus", window="address:"+address)
                    h.eval('hl.dispatch(hl.dsp.layout("colresize 0.78"))')
                # Finish the client's initial map/configure before comparing
                # parking with a stable tiled allocation below its minimum.
                time.sleep(.4)
                before = h.client(address)
                assert not before["floating"] and before["size"][0] < 320, before
                for cycle in range(3):
                    record = session.park(address)
                    parked = h.client(address)
                    assert parked["floating"] and parked["workspace"]["name"] == SPECIAL
                    assert parked["size"][0] > before["size"][0], (before["size"], parked["size"])
                    assert all(actual >= saved for actual, saved in zip(parked["size"], before["size"]))
                    assert record["size"] == before["size"] and not record["floating"] and record["phase"] == "stashed"
                    saved = next(item for item in command("list")["windows"] if item["id"] == record["id"])
                    assert saved == record, "Reconciliation rewrote constrained-source restoration metadata"
                    command("restore", record["id"], "--to", "original")
                    def restored():
                        client = h.client(address)
                        return client if (client and not client["floating"]
                                          and client["workspace"]["id"] == session.workspace
                                          and all(abs(a-b) <= 1 for a, b in zip(client["size"], before["size"]))) else None
                    wait(restored, "Original narrow tiled geometry did not restore")
                    assert not any(item["id"] == record["id"] for item in command("list")["windows"])
                print("PASS", layout, "three minimum-clamped parking/restoration cycles; original allocation",
                      before["size"], "working size", parked["size"], flush=True)
                h.dispatch("window.close", window="address:"+address)
                wait(lambda: h.client(address) is None, "Constraint fixture did not close")
        finally:
            h.eval("if _G."+rule_key+" then for _,rule in ipairs(_G."+rule_key
                   +") do rule:set_enabled(false) end;_G."+rule_key+"=nil end")
            session.monitor, session.workspace = original_monitor, original_workspace


if __name__ == "__main__":
    main()
