from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from project_lanes import LaneClaim, LaneKind, admit_writer, paths_overlap


class CooperativeLaneTests(unittest.TestCase):
    def claim(self, name, writes, kind=LaneKind.WORKER, role=None):
        if role is None:
            role = "review" if kind == LaneKind.REVIEW else ("integrator" if kind == LaneKind.INTEGRATOR else "writer")
        return LaneClaim(
            lane_id=name,
            invocation_id=name,
            kind=kind,
            source_head="a" * 40,
            worktree=name,
            branch=name,
            write_paths=frozenset(writes),
            role=role,
        )

    def test_disjoint_writers_can_coexist(self):
        self.assertTrue(admit_writer([self.claim("a", {"src/a"})], self.claim("b", {"src/b"})))

    def test_parent_child_paths_overlap(self):
        self.assertTrue(paths_overlap(self.claim("a", {"src"}), self.claim("b", {"src/a"})))
        self.assertFalse(admit_writer([self.claim("a", {"src"})], self.claim("b", {"src/a"})))

    def test_portable_case_and_unicode_variants_overlap(self):
        self.assertTrue(paths_overlap(self.claim("a", {"SRC/Feature"}), self.claim("b", {"src/feature"})))
        self.assertTrue(paths_overlap(self.claim("a", {"docs/café"}), self.claim("b", {"docs/cafe\u0301"})))

    def test_read_only_lane_does_not_block_writer(self):
        self.assertTrue(admit_writer([self.claim("review", set(), LaneKind.REVIEW)], self.claim("worker", {"src/a"})))

    def test_review_kind_cannot_gain_write_authority_from_write_paths(self):
        with self.assertRaisesRegex(ValueError, "review|write"):
            admit_writer([], self.claim("review-writer", {"src/a"}, LaneKind.REVIEW, role="review"))

    def test_review_kind_rejects_writer_role_even_without_write_paths(self):
        with self.assertRaisesRegex(ValueError, "review|role"):
            admit_writer([], self.claim("review-role", set(), LaneKind.REVIEW, role="writer"))

    def test_read_only_role_cannot_carry_write_paths(self):
        with self.assertRaisesRegex(ValueError, "read|write|role"):
            admit_writer([], self.claim("observer-writer", {"src/a"}, LaneKind.WORKER, role="observer"))

    def test_ordinary_writer_authority_is_preserved(self):
        writer = self.claim("writer", {"src/a"}, LaneKind.WORKER, role="writer")
        self.assertTrue(writer.is_writer)
        self.assertTrue(admit_writer([], writer))

    def test_unknown_role_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "role"):
            admit_writer([], self.claim("custom", {"src/a"}, LaneKind.WORKER, role="custom-authority"))

    def test_unsafe_git_branch_names_are_rejected(self):
        for branch_name in ("--force", "refs/tags/not-a-lane", "refs/heads/bad ref",
                            "refs/heads/a..b", "refs/heads/.hidden"):
            value = self.claim("unsafe", {"src/a"})
            value = LaneClaim(
                lane_id=value.lane_id, invocation_id=value.invocation_id,
                kind=value.kind, source_head=value.source_head,
                worktree=value.worktree, branch=branch_name,
                write_paths=value.write_paths)
            with self.subTest(branch=branch_name), self.assertRaises(ValueError):
                admit_writer([], value)

    def test_integrator_is_singleton(self):
        existing = self.claim("i1", set(), LaneKind.INTEGRATOR)
        candidate = self.claim("i2", set(), LaneKind.INTEGRATOR)
        self.assertFalse(admit_writer([existing], candidate))


if __name__ == "__main__":
    unittest.main()
