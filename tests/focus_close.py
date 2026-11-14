#!/usr/bin/env python3
"""An owned hidden source closing must not restore another stashed window."""
import os
from pathlib import Path
import time

from desktop_test import desktop_test
from live import command, configure, h, shell, wait
from native_session import NativeSession
from stash import FOCUS_GUARD, SPECIAL


def cleared():
    return int(h.call("repl", "local g="+FOCUS_GUARD+"; return g and g.cleared or 0"))


@desktop_test("Owned hidden-window close and external activation safety")
def main():
    assert os.environ.get("WINDOW_STASH_ISOLATED_TEST") == "1" and (Path.home()/".window-stash-isolated").is_file(), \
        "Use an explicit disposable compositor"
    with NativeSession() as session:
        for name, value in dict(presentation="floating", animations="off", hoverPreview="off",
                                floatingPlacement="free", dragMotion="direct").items():
            configure(name, value)
        addresses, records = [], []
        for _ in range(3):
            address, _ = session.spawn(app="org.windowstash.CloseFocusSafety")
            addresses.append(address)
            records.append(session.park(address))
        session.click(session.dock()["handle"])
        wait(lambda: session.dock()["expanded"], "Close-safety fan did not unfold")
        # Test the persistent OnDemand phase, after the short Exclusive primer
        # that independently blocks compositor focus fallback during opening.
        time.sleep(.15)
        active = h.read("activewindow").get("address")
        target = active if active in addresses else addresses[0]
        expected_guard = active == target
        closed = next(record for record in records if record["address"] == target)
        survivors = [record for record in records if record["id"] != closed["id"]]
        before = cleared()
        h.dispatch("window.close", window="address:"+target)
        wait(lambda: h.client(target) is None, "Hidden owned source did not close")
        # Let the ordinary external-activation timer run too: the guard must
        # prevent that delayed recovery from promoting an unrelated source.
        time.sleep(.35)
        assert {record["id"] for record in command("list")["windows"]} == {record["id"] for record in survivors}
        assert all(h.client(record["address"])["workspace"]["name"] == SPECIAL for record in survivors)
        assert all((monitor.get("specialWorkspace") or {}).get("name") != SPECIAL for monitor in h.read("monitors"))
        if expected_guard:
            assert cleared() > before, "The native close witness did not run the owned overlay guard"
        print("PASS exact owned closure preserves neighboring private records and never opens their workspace", flush=True)

        shell("dismiss")
        session.keys("-k", "Escape")
        restored, neighbor = survivors
        h.dispatch("focus", window="address:"+restored["address"])
        wait(lambda: h.client(restored["address"])["workspace"]["id"] == session.workspace
             and all(record["id"] != restored["id"] for record in command("list")["windows"]),
             "A completed close guard blocked deliberate external activation")
        assert h.client(neighbor["address"])["workspace"]["name"] == SPECIAL
        print("PASS deliberate external activation restores only its requested window", flush=True)

        public, _ = session.spawn(app="org.windowstash.PublicCloseSafety")
        h.dispatch("window.close", window="address:"+public)
        wait(lambda: h.client(public) is None, "Public control window did not close")
        time.sleep(.2)
        assert h.client(neighbor["address"])["workspace"]["name"] == SPECIAL
        print("PASS public window closure does not change the remaining stash", flush=True)
    h.clear_focus_guard()
    assert h.call("repl", "return "+FOCUS_GUARD+"==nil") == "true"
    print("PASS owned focus observers and pending timers release without native preview support", flush=True)


if __name__ == "__main__":
    main()
