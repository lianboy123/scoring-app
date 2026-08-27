"""不接触正式数据库的基础冒烟测试。"""
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from app import create_app
from extensions import db
from models import Admin, AssignmentRule, Claim, Notification, ScoreRecord, Setting, Student


class AppSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
            "CLAIM_UPLOAD_DIR": str(Path(self.temp_dir.name) / "claim-images"),
        })
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_all_routes_are_registered(self) -> None:
        rules = {rule.rule for rule in self.app.url_map.iter_rules()}
        required = {
            "/admin/", "/admin/bulk_add", "/admin/manage/<category>",
            "/admin/records", "/admin/students/export", "/admin/settings",
            "/admin/claims", "/claims", "/public/student/<int:student_id>/<category>",
        }
        self.assertTrue(required.issubset(rules))

    def test_fresh_install_page_opens(self) -> None:
        response = self.client.get("/install")
        self.assertEqual(response.status_code, 200)

    def test_uninitialized_site_redirects_to_install(self) -> None:
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/install"))

    def test_admin_pages_render(self) -> None:
        self._seed_site()
        response = self.client.post("/admin/login", data={
            "username": "tester",
            "password": "test-password",
        })
        self.assertEqual(response.status_code, 302)

        pages = (
            "/admin/", "/admin/students", "/admin/upload", "/admin/records",
            "/admin/bulk_add", "/admin/export",
            "/admin/logs", "/admin/settings", "/admin/claims",
        )
        for page in pages:
            with self.subTest(page=page):
                self.assertEqual(self.client.get(page).status_code, 200)
        self.assertEqual(self.client.get("/admin/admins").status_code, 302)
        self.assertEqual(self.client.get("/admin/manage/growth").status_code, 302)
        self.assertEqual(self.client.get("/admin/claims?category=growth").status_code, 200)
        self.assertEqual(self.client.get("/admin/students/export").status_code, 200)

    def test_behavior_batch_accepts_different_points(self) -> None:
        self._seed_site()
        with self.app.app_context():
            second = Student(student_no="20260002", name="第二学生")
            db.session.add(second)
            db.session.commit()
            students = Student.query.order_by(Student.student_no).all()
        self.client.post("/admin/login", data={
            "username": "tester", "password": "test-password",
        })
        response = self.client.post("/admin/bulk_add", data={
            "activity_name": "差异分值活动",
            "semester": "2026-spring",
            "student_ids": [str(students[0].id), str(students[1].id)],
            f"points_{students[0].id}": "0.5",
            f"points_{students[1].id}": "1.25",
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            points = [float(row.points) for row in ScoreRecord.query
                      .filter_by(activity_name="差异分值活动")
                      .order_by(ScoreRecord.student_id).all()]
            self.assertEqual(points, [0.5, 1.25])

    def test_regular_admin_cannot_open_settings(self) -> None:
        self._seed_site()
        with self.app.app_context():
            regular = Admin(username="regular", is_super=False)
            regular.set_password("test-password")
            db.session.add(regular)
            db.session.commit()
        self.client.get("/admin/logout")
        self.client.post("/admin/login", data={
            "username": "regular", "password": "test-password",
        })
        self.assertEqual(self.client.get("/admin/settings").status_code, 403)

    def test_student_pages_render(self) -> None:
        self._seed_site()
        response = self.client.post("/login", data={
            "student_no": "20260001",
            "name": "测试学生",
        })
        self.assertEqual(response.status_code, 302)

        for page in ("/", "/announcements", "/ranking", "/claims"):
            with self.subTest(page=page):
                self.assertEqual(self.client.get(page).status_code, 200)
        self.assertEqual(self.client.get("/me").status_code, 302)

    def test_new_semester_and_claim_review_flow(self) -> None:
        self._seed_site()
        with self.app.app_context():
            reviewer = Admin(username="reviewer", is_super=False)
            reviewer.set_password("test-password")
            db.session.add(reviewer)
            db.session.flush()
            db.session.add(AssignmentRule(
                start_no="20260000", end_no="20269999", admin_id=reviewer.id,
            ))
            db.session.commit()
            reviewer_id = reviewer.id

        self.client.post("/admin/login", data={
            "username": "tester", "password": "test-password",
        })
        response = self.client.post("/admin/settings/semester", data={
            "semester": "2026-fall",
        })
        self.assertEqual(response.status_code, 302)
        self.client.get("/admin/logout")

        self.client.post("/login", data={
            "student_no": "20260001", "name": "测试学生",
        })
        response = self.client.post("/claims", data={
            "category": "innovation",
            "title": "数学建模竞赛",
            "proof": (BytesIO(b"fake-png"), "proof.png", "image/png"),
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            claim = Claim.query.one()
            self.assertEqual(claim.assigned_admin_id, reviewer_id)
            claim_id = claim.id

        self.client.post("/admin/login", data={
            "username": "reviewer", "password": "test-password",
        })
        response = self.client.post(f"/admin/claims/{claim_id}/review", data={
            "action": "approve", "points": "2.5", "is_public": "1",
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            claim = db.session.get(Claim, claim_id)
            self.assertEqual(claim.status, "approved")
            record = db.session.get(ScoreRecord, claim.score_record_id)
            self.assertEqual(record.category, "innovation")
            self.assertEqual(float(record.points), 2.5)
            self.assertTrue(record.is_public)
            self.assertTrue(Notification.query.filter(
                Notification.content.like("%已通过%")
            ).first())

    def _seed_site(self) -> None:
        with self.app.app_context():
            admin = Admin(username="tester", is_super=True)
            admin.set_password("test-password")
            student = Student(student_no="20260001", name="测试学生")
            db.session.add_all([admin, student])
            db.session.flush()
            Setting.set("current_semester", "2026-spring")
            db.session.add(ScoreRecord(
                student_id=student.id,
                activity_name="测试活动",
                points=1,
                semester="2026-spring",
                operator_id=admin.id,
            ))
            db.session.commit()


if __name__ == "__main__":
    unittest.main()
