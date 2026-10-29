from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import patch
from risk.services.kpmr_incomplete_email import recipient_lists, send_notification


def user(pk, email, active=True):
    return NS(pk=pk, email=email, is_active=active)


def assignment(role, person):
    return NS(peran=role, user=person)


class RecipientTests(TestCase):
    def data(self):
        officer=user(1,'officer@example.com')
        champion=user(2,'champion@example.com')
        pairing=user(3,'pairing@example.com')
        approver=user(4,'approver@example.com')
        return [assignment('RISK_OFFICER',officer), assignment('RISK_CHAMPION',champion), assignment('PAIRING_OFFICER',pairing)],champion,approver

    def test_required_roles_and_cc(self):
        result=recipient_lists(*self.data())
        self.assertEqual(result['to'],['officer@example.com'])
        self.assertEqual(set(result['cc']),{'champion@example.com','pairing@example.com','approver@example.com'})
        self.assertFalse(result['warnings'])

    def test_multiple_officers(self):
        assignments,reviewer,approver=self.data()
        assignments.append(assignment('RISK_OFFICER',user(5,'other@example.com')))
        self.assertEqual(len(recipient_lists(assignments,reviewer,approver)['to']),2)

    def test_duplicate_to_not_in_cc(self):
        assignments,reviewer,approver=self.data()
        approver.email='OFFICER@example.com'
        result=recipient_lists(assignments,reviewer,approver)
        self.assertNotIn('officer@example.com',result['cc'])

    def test_inactive_user_excluded(self):
        assignments,reviewer,approver=self.data()
        assignments[0].user.is_active=False
        result=recipient_lists(assignments,reviewer,approver)
        self.assertEqual(result['to'],[])
        self.assertTrue(result['warnings'])

    def test_missing_pairing_warned(self):
        assignments,reviewer,approver=self.data()
        result=recipient_lists(assignments[:2],reviewer,approver)
        self.assertTrue(any('Pairing Officer' in message for message in result['warnings']))

    def test_invalid_address_excluded(self):
        assignments,reviewer,approver=self.data()
        approver.email='broken'
        result=recipient_lists(assignments,reviewer,approver)
        self.assertNotIn('broken',result['cc'])
        self.assertTrue(result['warnings'])

    @patch('risk.services.kpmr_incomplete_email.EmailMultiAlternatives')
    def test_no_officer_never_sends(self, mail):
        with self.assertRaises(ValueError):
            send_notification({'to':[], 'cc':[]})
        mail.assert_not_called()
