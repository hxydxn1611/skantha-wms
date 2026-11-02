import unittest
import json
import io
import os
import sys
import cv2
import numpy as np

# Ensure webapp is in path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(ROOT_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

os.environ['FLASK_SECRET_KEY'] = 'test-secret-key-2026'

from app import app
import db

class TestAuthAndUpload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        db.init_db()

    def setUp(self):
        self.client = app.test_client()

    def test_01_unauthenticated_dashboard_redirects_to_login(self):
        """Unauthenticated GET to / must redirect to /login (Issue 1)"""
        response = self.client.get('/', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    def test_02_unauthenticated_api_returns_401(self):
        """Protected API endpoints must reject unauthenticated requests with HTTP 401 (Issue 1)"""
        endpoints = [
            ('/api/bins', 'GET'),
            ('/api/stats', 'GET'),
            ('/api/skus', 'GET'),
            ('/api/warehouses', 'GET'),
            ('/api/pallets/count-pieces', 'POST'),
            ('/api/pallets/count-bundles', 'POST'),
            ('/api/pallets/count-multiview', 'POST')
        ]
        for url, method in endpoints:
            with self.subTest(url=url, method=method):
                if method == 'GET':
                    resp = self.client.get(url)
                else:
                    resp = self.client.post(url, data={})
                self.assertEqual(resp.status_code, 401, f"Expected 401 for {url} but got {resp.status_code}")
                data = resp.get_json()
                self.assertIsNotNone(data)
                self.assertFalse(data.get('success', True))
                self.assertEqual(data.get('error_code'), 'unauthenticated')

    def test_03_public_endpoints_accessible(self):
        """Public authentication, registration, and discovery routes must remain open"""
        # GET /login
        resp = self.client.get('/login')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Sign In', resp.data)

        # POST /api/company/preview_recognition
        resp = self.client.post('/api/company/preview_recognition', json={'company_name': 'Saint Gobain Glass'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))

    def test_04_login_validation_and_session_creation(self):
        """Valid credentials must establish session; invalid credentials must fail"""
        # Invalid login
        resp = self.client.post('/api/login', json={'username': 'admin', 'password': 'wrongpassword'})
        self.assertEqual(resp.status_code, 401)

        # Valid login with default admin credentials
        resp = self.client.post('/api/login', json={'username': 'admin', 'password': 'admin'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('user', data)
        self.assertEqual(data['user']['username'], 'admin')

        # Now client has active session: GET / should return 200 (dashboard)
        dash_resp = self.client.get('/')
        self.assertEqual(dash_resp.status_code, 200)
        self.assertIn(b'W.A.R.L.O.G', dash_resp.data)

        # Logged-in user visiting /login should be redirected to /
        login_resp = self.client.get('/login', follow_redirects=False)
        self.assertEqual(login_resp.status_code, 302)
        self.assertEqual(login_resp.headers.get('Location'), '/')

        # Protected APIs should now succeed
        stats_resp = self.client.get('/api/stats')
        self.assertEqual(stats_resp.status_code, 200)

    def test_05_logout_invalidates_session(self):
        """Logout must clear session and subsequent requests must be rejected"""
        # Login first
        login_resp = self.client.post('/api/login', json={'username': 'admin', 'password': 'admin'})
        self.assertEqual(login_resp.status_code, 200)

        # Logout via API
        logout_resp = self.client.post('/api/logout')
        self.assertEqual(logout_resp.status_code, 200)

        # Subsequent GET / must redirect to /login
        dash_resp = self.client.get('/', follow_redirects=False)
        self.assertEqual(dash_resp.status_code, 302)
        self.assertIn('/login', dash_resp.headers.get('Location', ''))

        # Subsequent API call must return 401
        api_resp = self.client.get('/api/stats')
        self.assertEqual(api_resp.status_code, 401)

    def test_06_authenticated_pallet_image_upload_pieces(self):
        """Pallet vision counting workbench must accept uploaded image for authenticated user (Issue 2)"""
        # Authenticate
        self.client.post('/api/login', json={'username': 'admin', 'password': 'admin'})

        # Create a synthetic test image with circular pipes
        img = np.full((300, 300, 3), 40, dtype=np.uint8)
        cv2.circle(img, (100, 100), 25, (220, 220, 220), -1)
        cv2.circle(img, (100, 100), 18, (30, 30, 30), -1)
        cv2.circle(img, (200, 100), 25, (220, 220, 220), -1)
        cv2.circle(img, (200, 100), 18, (30, 30, 30), -1)
        _, img_bytes = cv2.imencode('.jpg', img)

        payload = {
            'counting_mode': 'pieces',
            'material_type': 'individual_pieces',
            'source_type': 'upload',
            'image': (io.BytesIO(img_bytes.tobytes()), 'test_pallet_pipes.jpg')
        }

        resp = self.client.post('/api/pallets/count-pieces', data=payload, content_type='multipart/form-data')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertTrue('total_pieces' in data or 'primary_count' in data)
        self.assertIn('pieces', data)
        self.assertIn('annotated_image_url', data)

    def test_07_authenticated_pallet_image_upload_bundles(self):
        """Pallet bundle counting must accept uploaded image for authenticated user (Issue 2)"""
        # Authenticate
        self.client.post('/api/login', json={'username': 'admin', 'password': 'admin'})

        # Synthetic image
        img = np.full((300, 300, 3), 50, dtype=np.uint8)
        cv2.rectangle(img, (50, 50), (250, 120), (180, 180, 180), -1)
        cv2.rectangle(img, (50, 150), (250, 220), (180, 180, 180), -1)
        _, img_bytes = cv2.imencode('.png', img)

        payload = {
            'counting_mode': 'bundles',
            'material_type': 'metal_bundles',
            'source_type': 'upload',
            'image': (io.BytesIO(img_bytes.tobytes()), 'test_bundle.png')
        }

        resp = self.client.post('/api/pallets/count-bundles', data=payload, content_type='multipart/form-data')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertTrue('total_bundles' in data or 'primary_count' in data)

if __name__ == '__main__':
    unittest.main()
