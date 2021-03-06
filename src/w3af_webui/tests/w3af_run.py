#-*- coding: utf-8 -*-
import os
from mock import patch
from shutil import rmtree

from django.test import TestCase
from django_any.models import any_model
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command

from w3af_webui.management.commands.w3af_run import fail_scan
from w3af_webui.management.commands.w3af_run import get_profile
from w3af_webui.management.commands.w3af_run import get_report_path
from w3af_webui.management.commands.w3af_run import send_notification
from w3af_webui.management.commands.w3af_run import post_finish
from w3af_webui.management.commands.w3af_run import save_vulnerabilities
from w3af_webui.models import ScanTask
from w3af_webui.models import Target
from w3af_webui.models import ScanProfile
from w3af_webui.models import ProfilesTasks
from w3af_webui.models import Scan
from w3af_webui.models import Vulnerability

class TestW3afRun(TestCase):
    def setUp(self):
        Scan.objects.all().delete()
        user = User.objects.create_user('svetleo', 'user@example.com', '!')
        user.save()
        self.target = any_model(Target)
        self.scan_task = any_model(ScanTask,
                                   user=user,
                                   status=settings.TASK_STATUS['free'],
                                   target=self.target,
                                   last_updated='0',
                                   cron="",)
        self.scan = Scan.objects.create(
                                scan_task=self.scan_task,
                                data='test',
                                status=settings.SCAN_STATUS['in_process'])

    @patch('w3af_webui.notification.send_mail.notify')
    def test_send_notification(self, mock_send_mail):
        # notification = None
        none_index = max(index for index, value in enumerate(settings.NOTIFY_MODULES)
                         if value['id'] == 'None')
        user = self.scan_task.user
        user.get_profile().notification = none_index # None
        user.save()
        result = send_notification(self.scan)
        self.assertTrue(result)
        self.assertFalse(mock_send_mail.called)
        # fake notification
        user.get_profile().notification = 10000 # fake 
        user.save()
        result = send_notification(self.scan)
        self.assertFalse(result)
        self.assertFalse(mock_send_mail.called)
        # notification = Mail
        mail_index = max(index for index, value in enumerate(settings.NOTIFY_MODULES)
                         if value['id'] == 'Mail')
        user.get_profile().notification = mail_index # Mail
        user.save()
        result = send_notification(self.scan)
        self.assertTrue(result)
        self.assertTrue(mock_send_mail.called)

    def test_get_profile(self):
        scan_profile = any_model(ScanProfile)
        any_model(ProfilesTasks,
                  scan_task=self.scan_task,
                  scan_profile=scan_profile)
        (profile_name, xml_report) = get_profile(self.scan_task,
                                                 '/var/tmp',
                                                 'test.html')
        #check that this file exist
        self.assertTrue(os.access(profile_name, os.F_OK))

    def test_get_report_path(self):
        report_path = get_report_path()
        self.assertTrue(os.access(report_path, os.F_OK))

    @patch('w3af_webui.models.Scan.set_task_status_free')
    def test_fail_scan(self, mock_status_free):
        scan = Scan.objects.create(scan_task=self.scan_task, data='test',
                                        status=settings.SCAN_STATUS['in_process'])
        self.assertEqual(scan.status, settings.SCAN_STATUS['in_process'])
        self.assertFalse(mock_status_free.called)
        old_result_message = scan.result_message
        new_result_message = 'test msg'
        fail_scan(scan.id, new_result_message)
        scan = Scan.objects.get(pk=int(scan.id))
        #Assert after call
        self.assertTrue(mock_status_free.called)
        self.assertEqual(scan.status, settings.SCAN_STATUS['fail'])
        self.assertEqual(scan.result_message,
                         old_result_message + new_result_message )

    def test_scan_does_not_exist(self):
        #scan does not exist
        self.assertRaises(Scan.DoesNotExist, call_command,
                          'w3af_run', -1)

    @patch('w3af_webui.management.commands.w3af_run.get_report_path')
    @patch('w3af_webui.management.commands.w3af_run.fail_scan')
    def test_w3af_run_exceptions_raises(self, mock_fail_scan, mock_get_report):
        exc = Exception('Boom!')
        mock_get_report.side_effect = exc
        self.assertRaises(Exception, call_command,
                          'w3af_run', self.scan.id)
        self.scan = Scan.objects.get(pk=int(self.scan.id))
        self.assertTrue(mock_fail_scan.called)

    def test_w3af_scan_does_not_exist(self):
        #scan does not exist
        self.assertRaises(Scan.DoesNotExist, call_command, 'w3af_run', -1)

    @patch('w3af_webui.management.commands.w3af_run.wait_process_finish')
    @patch('w3af_webui.management.commands.w3af_run.post_finish')
    @patch('w3af_webui.management.commands.w3af_run.get_profile')
    @patch('w3af_webui.management.commands.w3af_run.get_report_path')
    def test_w3af_run(self, mock_report_path, mock_get_profile,
                      mock_post_finish, mock_wait_process):
        test_report_path = 'test_report/'
        try:
            os.mkdir(test_report_path)
        except Exception, e:
            print e
        mock_report_path.return_value = test_report_path
        mock_get_profile.return_value = ('test.html', 'test.xml')
        # process terminated with error
        mock_wait_process.return_value = 1 # return error
        call_command('w3af_run', self.scan.id)
        self.assertTrue(mock_wait_process.called)
        self.assertTrue(mock_post_finish.called)
        # process terminated without error
        rmtree(test_report_path)

    @patch('w3af_webui.management.commands.w3af_run.fail_scan')
    @patch('w3af_webui.management.commands.w3af_run.save_vulnerabilities')
    def test_post_finish(self, mock_save_vuln, mock_fail_scan):
        # bad returncode
        self.assertFalse(mock_fail_scan.called)
        self.assertFalse(mock_save_vuln.called)
        mock_save_vuln.return_value = True
        post_finish(self.scan, -9, 'test.xml')
        self.assertTrue(mock_fail_scan.called)
        # returncode ok, but task was stoped by user 
        self.scan.status = settings.SCAN_STATUS['fail']
        self.scan.save()
        mock_fail_scan.reset_mock()
        post_finish(self.scan, 0, 'test.xml')
        self.assertFalse(mock_fail_scan.called)
        self.assertEqual(Scan.objects.get(pk=int(self.scan.id)).status,
                         settings.SCAN_STATUS['fail'])
        # ok returncode and status
        mock_fail_scan.reset_mock()
        self.scan.status = settings.SCAN_STATUS['in_process']
        self.scan.save()
        post_finish(self.scan, 0, 'test.xml')
        self.assertFalse(mock_fail_scan.called)
        self.assertEqual(Scan.objects.get(pk=int(self.scan.id)).status,
                          settings.SCAN_STATUS['done'])

    def test_save_vulner(self):
        Vulnerability.objects.all().delete
        test_xml = open('/var/tmp/test.xml', 'w')
        test_xml.write(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w3afrun start="1334319384">'
            '<vulnerability id="[106]" method="GET" name="test"'
            ' plugin="xss" severity="Medium" >'
            '<description>'
            'test desc'
            '</description>'
            '<httprequest id="106">'
            '<status>'
            'tttttt'
            '</status>'
            '<headers>'
            '<header content="test.test-domain.ru" field="Host"/>'
            '</headers>'
            '</httprequest>'
            '</vulnerability>'
            '</w3afrun>'
            )
        test_xml.close()
        result = save_vulnerabilities(self.scan, test_xml.name)
        self.assertEqual(
            Vulnerability.objects.filter(scan=self.scan).count(), 1)
        self.assertTrue(result)


    def test_save_vulner_not_found(self):
        Vulnerability.objects.all().delete
        test_xml = open('/var/tmp/test.xml', 'w')
        test_xml.write(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w3afrun start="1334319384">'
            '</w3afrun>'
            )
        test_xml.close()
        result = save_vulnerabilities(self.scan, test_xml.name)
        self.assertEqual(
            Vulnerability.objects.filter(scan=self.scan).count(), 0)
        self.assertTrue(result)

    def test_save_vulner_fail(self):
        test_xml = open('/var/tmp/test.xml', 'w')
        # wrong xml
        test_xml.write('wrong string')
        test_xml.close()
        result = save_vulnerabilities(self.scan, test_xml.name)
        self.assertFalse(result)

    def tearDown(self):
        self.scan.delete()
        self.scan_task.delete()
        self.target.delete()
        Scan.objects.all().delete()


