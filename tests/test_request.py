import json
import os
import stat

from hermes_controller import request as req
from tests.helpers import HomeCase

DOC = json.loads((__import__("pathlib").Path(__file__).resolve().parent.parent / "contracts" / "request.v1.json").read_text())


class RequestTest(HomeCase):
    def setUp(self):
        super().setUp()
        self.dir = self.home / "controller" / "requests"

    def test_contract_example_round_trips(self):
        req.write_request(self.dir, DOC)
        r = req.read_request(self.dir, DOC["deliveryId"])
        self.assertEqual((r.route, r.repo, r.pr, r.target), ("testgate", "acme/shop", 7, "pull_request"))
        mode = stat.S_IMODE(os.stat(req.request_path(self.dir, DOC["deliveryId"])).st_mode)
        self.assertEqual(mode, 0o600)

    def test_second_write_of_same_id_is_refused(self):
        req.write_request(self.dir, DOC)
        with self.assertRaises(req.RequestError) as ctx:
            req.write_request(self.dir, DOC)
        self.assertEqual(ctx.exception.reason, req.REQUEST_EXISTS)

    def test_bad_values_are_rejected(self):
        bad = [dict(DOC, version=2), dict(DOC, deliveryId="other"), dict(DOC, repo="../x"), dict(DOC, pr=0),
               dict(DOC, pr=True), dict(DOC, target="commit"), dict(DOC, body=None), dict(DOC, route="")]
        for doc in bad:
            with self.subTest(doc=doc), self.assertRaises(req.RequestError):
                req.validated(doc, DOC["deliveryId"])

    def test_missing_and_symlinked_files(self):
        with self.assertRaises(req.RequestError) as ctx:
            req.read_request(self.dir, "d-none")
        self.assertEqual(ctx.exception.reason, req.REQUEST_MISSING)
        self.dir.mkdir(parents=True)
        real = self.home / "real.json"
        real.write_text(json.dumps(DOC))
        os.symlink(real, req.request_path(self.dir, DOC["deliveryId"]))
        with self.assertRaises(req.RequestError) as ctx:
            req.read_request(self.dir, DOC["deliveryId"])
        self.assertEqual(ctx.exception.reason, req.REQUEST_UNREADABLE)

    def test_bad_delivery_ids(self):
        for value in ("", "..", "a/b", "x" * 101, None):
            self.assertFalse(req.valid_delivery_id(value))
