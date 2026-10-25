import pytest

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset  # noqa: E402

from app.deid import deidentify_for_test  # noqa: E402


def test_deidentification_removes_direct_identifiers_and_private_tags():
    dataset = Dataset()
    dataset.PatientName = "Sensitive^Person"
    dataset.PatientID = "mrn-123456"
    dataset.PatientAge = "540M"
    dataset.Manufacturer = "Example Scanner Vendor"
    dataset.Modality = "CR"
    dataset.Rows = 1024
    dataset.Columns = 1024
    dataset.add_new((0x0011, 0x1010), "LO", "private-site-value")
    clean = deidentify_for_test(dataset, tenant_id="clinic-a")
    assert "PatientName" not in clean
    assert clean.PatientID != "mrn-123456"
    assert clean.PatientIdentityRemoved == "YES"
    assert clean.PatientAge == "045Y"
    assert clean.Manufacturer == "Example Scanner Vendor"
    assert clean.Modality == "CR"
    assert (0x0011, 0x1010) not in clean
