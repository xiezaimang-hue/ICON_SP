import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sheet_importer


class SheetImporterTests(unittest.TestCase):
    def test_csv_supports_forward_filled_city_and_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir, "pois.csv")
            path.write_text(
                "目的地,编号,地标\nSeoul,2,Gyeongbokgung Palace\n,1,Namsan Tower\n",
                encoding="utf-8",
            )
            city, pois = sheet_importer.extract_pois(path, "Seoul")
        self.assertEqual(city, "Seoul")
        self.assertEqual(pois, ["Namsan Tower", "Gyeongbokgung Palace"])

    def test_xlsx_auto_detects_header_sheet(self):
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir, "pois.xlsx")
            workbook = Workbook()
            ws = workbook.active
            ws.title = "导览卡图标"
            ws.append(["说明"])
            ws.append(["目的地", "编号", "地标"])
            ws.append(["Seoul", 1, "Namsan Tower"])
            workbook.save(path)
            city, pois = sheet_importer.extract_pois(path, "Seoul")
        self.assertEqual(city, "Seoul")
        self.assertEqual(pois, ["Namsan Tower"])


if __name__ == "__main__":
    unittest.main()
