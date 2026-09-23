import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from cosmos3.extend_all_city_pilot import eligible, extract_metadata


class ExtensionTests(unittest.TestCase):
    def test_exclusions(self):
        protected = dict(protected_public_source_logs=['public'],
                         protected_official_val_source_logs=['official'],
                         quarantined_mini_source_logs=['mini'],
                         protected_public_city_dates=[['vegas', '2021-01-01']])
        row = dict(eligible_metadata_candidate='True', exclusion_reasons='',
                   proposed_role='pilot_training', source_log='independent',
                   city='vegas', date='2021-07-09')
        eligible(row, protected)
        for log in ['public', 'official', 'mini']:
            with self.assertRaises(ValueError):
                eligible(dict(row, source_log=log), protected)
        with self.assertRaises(ValueError):
            eligible(dict(row, date='2021-01-01'), protected)

    def test_zip_identity_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / 'fixture.db'
            with sqlite3.connect(db_path) as db:
                db.execute('CREATE TABLE log (logfile TEXT, location TEXT, date TEXT)')
                db.execute('INSERT INTO log VALUES (?,?,?)',
                           ('window', 'las_vegas', '2021-07-09'))
            archive_path = root / 'fixture.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.write(db_path, 'nested/window.db')
                info = archive.getinfo('nested/window.db')
                row = dict(archive=str(archive_path), member=info.filename,
                           uncompressed_bytes=str(info.file_size), zip_crc=str(info.CRC),
                           recording_window='window', date='2021-07-09')
            output = root / 'out/window.db'
            result = extract_metadata(row, output)
            self.assertEqual(Path(result['path']).read_bytes(), db_path.read_bytes())
            with self.assertRaises(ValueError):
                extract_metadata(row, output)
            with self.assertRaises(ValueError):
                extract_metadata(dict(row, date='incorrect'), root / 'wrong.db')
            with self.assertRaises(ValueError):
                extract_metadata(dict(row, zip_crc='0'), root / 'bad-crc.db')


if __name__ == '__main__':
    unittest.main()
