from django.test import TestCase, override_settings

from risk.models import AppSetting


TEST_ENCRYPTION_KEY = "F4ME9LRv7d0aAqxRhC49wa8oI9VPDgruGuZVXh_LraE="


@override_settings(APP_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class AppSettingSecretEncryptionTests(TestCase):
    def test_ai_and_smtp_secrets_are_encrypted_at_rest_and_decrypted_at_runtime(self):
        setting = AppSetting.get_solo()
        setting.ai_api_key = "ai-secret-example"
        setting.email_host_password = "smtp-secret-example"
        setting.save()

        setting.refresh_from_db()

        self.assertTrue(setting.ai_api_key.startswith("fernet:v1:"))
        self.assertTrue(setting.email_host_password.startswith("fernet:v1:"))
        self.assertNotIn("ai-secret-example", setting.ai_api_key)
        self.assertNotIn("smtp-secret-example", setting.email_host_password)
        self.assertEqual(setting.runtime_ai_api_key, "ai-secret-example")
        self.assertEqual(setting.runtime_email_host_password, "smtp-secret-example")
        self.assertNotIn("ai-secret-example", setting.masked_ai_api_key)
        self.assertNotIn("smtp-secret-example", setting.masked_email_host_password)

    def test_repeated_save_does_not_double_encrypt_existing_ciphertext(self):
        setting = AppSetting.get_solo()
        setting.ai_api_key = "same-secret"
        setting.save()
        first_ciphertext = setting.ai_api_key

        setting.nama_aplikasi = "ERM Test"
        setting.save()
        setting.refresh_from_db()

        self.assertEqual(setting.ai_api_key, first_ciphertext)
        self.assertEqual(setting.runtime_ai_api_key, "same-secret")
