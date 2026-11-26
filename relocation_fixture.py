"""Build an ordinary V1 exhibit layout for swap scenarios over the existing HTTP API."""

from tests.support import Forms, SiteCase, group


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


class RelocationSwapCase(SiteCase):
    def setUp(self):
        super().setUp()
        self.fixture = prepare(self)
        self.i1 = self.fixture["installations"]["R1"]["id"]
        self.i2 = self.fixture["installations"]["R2"]["id"]
        self.r3 = self.fixture["handoffs"]["R3"]
        self.targets = [
            {"installation_id": self.i1, "base_id": "U2"},
            {"installation_id": self.i2, "base_id": "U1"},
        ]

    def complete(self, plan_id):
        plan = self.get(f"/relocations/{plan_id}")
        for _ in range(8):
            if plan["state"] == "completed":
                return plan
            plan = self.post(f"/relocations/{plan_id}/moves", plan["next_move"])
        raise AssertionError("swap plan did not complete")

    def test_checkout_confirm_reopen_closeout_and_actual_removal(self):
        before = self.post("/closeouts", {"exhibition": "river"})
        for buffers in ((), ["V1"]):
            self.post("/relocations", {
                "exhibition": "river", "targets": self.targets, "buffers": buffers,
            }, status=409)

        plan = self.post("/relocations", {
            "exhibition": "river", "targets": self.targets, "buffers": ["S"],
        })
        plan_id = plan["id"]
        first = {"step": 1, "installation_id": self.i1,
                 "from_base_id": "U1", "to_base_id": "S"}
        self.assertEqual(first, plan["next_move"])

        self.mount(self.r3, base="S", status=409)
        self.post("/parts/availability",
                  {"kind": "base", "id": "S", "active": False}, status=409)
        self.remove(self.i1, status=409)
        outside = self.mount(self.r3, base="F")

        page = self.get(f"/relocations/{plan_id}", html=True)
        form = Forms(page).get(f"/relocations/{plan_id}/moves", "post")
        self.post(f"/relocations/{plan_id}/moves", form["inputs"], form=True, html=True)
        self.assertEqual([("S", self.i1), ("U2", self.i2)], self.rows(
            "SELECT base_id, installation_id FROM base_occupancy "
            "WHERE base_id IN ('S', 'U1', 'U2') ORDER BY base_id"))
        mid = self.post("/closeouts", {"exhibition": "river"})
        mid_entry = next(row for row in mid["categories"]["mounted"]
                         if row["installation"]["id"] == self.i1)
        self.assertEqual("S", mid_entry["actual_base_id"])

        self.reopen()
        self.post(f"/relocations/{plan_id}/moves", first, status=409)
        completed = self.complete(plan_id)
        self.assertEqual(3, len(completed["moves"]))
        self.assertEqual("completed", completed["state"])
        self.assertEqual([
            {"installation_id": self.i1, "base_id": "U2", "target_base_id": "U2"},
            {"installation_id": self.i2, "base_id": "U1", "target_base_id": "U1"},
        ], completed["positions"])

        after = self.post("/closeouts", {"exhibition": "river"})
        self.assertEqual(before, self.get(f"/closeouts/{before['id']}"))
        self.assertEqual(mid, self.get(f"/closeouts/{mid['id']}"))

        receipt1 = self.receipt(self.fixture["handoffs"]["R1"])
        receipt2 = self.receipt(self.fixture["handoffs"]["R2"])
        self.assertEqual("U1", receipt1["installation"]["base_id"])
        self.assertEqual("U2", receipt1["actual_base_id"])
        self.assertEqual(2, len(receipt1["moves"]))
        self.assertEqual("U2", receipt2["installation"]["base_id"])
        self.assertEqual("U1", receipt2["actual_base_id"])
        self.assertEqual(1, len(receipt2["moves"]))
        self.assertTrue(all(move["relocation_id"] == plan_id for move in receipt1["moves"]))

        self.remove(self.i1)
        self.remove(self.i2)
        self.assertEqual([], self.rows(
            "SELECT base_id FROM base_occupancy WHERE base_id IN ('U1', 'U2')"))
        removed1 = self.receipt(self.fixture["handoffs"]["R1"])
        self.assertEqual("removed", removed1["state"])
        self.assertEqual("U2", removed1["actual_base_id"])
        self.assertEqual(outside["handoff_id"], self.r3)
        self.assertEqual(after["id"], after["id"])
