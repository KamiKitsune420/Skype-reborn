import unittest
from shared.models import Envelope, MessageType, LoginPayload

class TestSharedModels(unittest.TestCase):
    def test_envelope_serialization(self):
        payload = {"username": "testuser", "password": "password123"}
        envelope = Envelope(
            type=MessageType.AUTH_LOGIN,
            payload=payload
        )
        json_data = envelope.model_dump_json()
        self.assertIn("AUTH_LOGIN", json_data)
        self.assertIn("testuser", json_data)

    def test_envelope_deserialization(self):
        json_data = '{"type": "AUTH_LOGIN", "payload": {"username": "testuser", "password": "password123"}}'
        envelope = Envelope.model_validate_json(json_data)
        self.assertEqual(envelope.type, MessageType.AUTH_LOGIN)
        self.assertEqual(envelope.payload["username"], "testuser")

if __name__ == "__main__":
    unittest.main()
