"""Build an ordinary V1 exhibit layout for swap scenarios over the existing HTTP API."""

from tests.support import SiteCase, group


def prepare(case, *, second_buffer=False):
    case.catalog()
    bases = ["F", "S"]
    if second_buffer:
        bases.append("W")
    for base_id in bases:
        case.post("/parts", {"kind": "base", "id": base_id, "slot": "u",
                             "minimum": 10, "maximum": 11})
    case.draft(groups=[group("A", "u", "Y"), group("A", "v")])
    old = case.issue()
    handoffs = {name: case.handoff(old, name) for name in ("R1", "R2", "R3")}
    installations = {
        "R1": case.mount(handoffs["R1"], base="U1"),
        "R2": case.mount(handoffs["R2"], base="U2"),
    }
    case.post("/parts/revise", {"kind": "base", "id": "v", "minimum": 10,
                                "maximum": 11}, status=200)
    case.draft("r2", parent="r1", groups=[group("A", "u", "X"), group("A", "v", "Y")])
    current = case.issue("r2")
    return {"old": old, "current": current, "handoffs": handoffs, "installations": installations}


class RelocationFixtureCase(SiteCase):
    def check_ordinary_use(self, second_buffer):
        fixture = prepare(self, second_buffer=second_buffer)
        for label, expected in (("old", {"u": ["X"], "v": ["Y"]}),
                                ("current", {"u": ["Y"], "v": ["X"]})):
            actual = {row["slot"]: row["allowed_pads"] for row in fixture[label]["groups"]}
            self.assertEqual(expected, actual)
        handoffs, installs = fixture["handoffs"], fixture["installations"]
        current = self.get("/editions/current", {"exhibition": "river"})
        self.assertEqual(fixture["current"]["id"], current["id"])
        initial = [("U1", installs["R1"]["id"]), ("U2", installs["R2"]["id"])]
        occupancy = "SELECT base_id, installation_id FROM base_occupancy ORDER BY base_id"
        self.assertEqual(initial, self.rows(occupancy))
        self.mount(handoffs["R1"], base="S", status=409)
        self.mount(handoffs["R3"], base="V1", status=409)
        self.assertEqual(initial, self.rows(occupancy))
        if second_buffer:
            options = self.get("/mounts", {"handoff_id": handoffs["R3"], "base_id": "W"})
            self.assertEqual(["X"], options["allowed_pads"])
        before = self.post("/closeouts", {"exhibition": "river"})
        third = self.mount(handoffs["R3"], base="S")
        self.assertEqual([("S", third["id"]), *initial], self.rows(occupancy))
        self.remove(installs["R1"]["id"])
        receipt = self.receipt(handoffs["R1"])
        self.assertEqual("removed", receipt["state"])
        self.assertTrue(receipt["ticket"]["ended"])
        self.assertEqual(installs["R1"], receipt["installation"])
        self.assertEqual(before, self.get("/closeouts/{}".format(before["id"])))

    def test_single_buffer(self):
        self.check_ordinary_use(False)

    def test_two_buffers(self):
        self.check_ordinary_use(True)
