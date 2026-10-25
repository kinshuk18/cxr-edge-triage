"""Write a deterministic synthetic chest-like CR DICOM (no patient data)."""

import argparse
from pathlib import Path

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid


def create_dicom(path: Path, monochrome1: bool = False):
    height, width = 1024, 768
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    radial = np.sqrt(((x - width / 2) / (width / 2)) ** 2 + ((y - height / 2) / (height / 2)) ** 2)
    anatomy = np.clip(0.8 - 0.5 * radial, 0.0, 1.0)
    lung_left = (((x - width * 0.34) / (width * 0.20)) ** 2 + ((y - height * 0.48) / (height * 0.31)) ** 2) < 1
    lung_right = (((x - width * 0.66) / (width * 0.20)) ** 2 + ((y - height * 0.48) / (height * 0.31)) ** 2) < 1
    anatomy[lung_left | lung_right] *= 0.55
    anatomy += 0.025 * np.sin(x / 15.0) * np.cos(y / 19.0)
    pixels = np.clip(anatomy * 65535.0, 0, 65535).astype(np.uint16)

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientName = "SYNTHETIC^NOT_REAL"
    ds.PatientID = "SYNTHETIC-ONLY-001"
    ds.PatientAge = "045Y"
    ds.Modality = "CR"
    ds.Manufacturer = "Synthetic Generator"
    ds.Rows = height
    ds.Columns = width
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME1" if monochrome1 else "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.BurnedInAnnotation = "NO"
    ds.WindowCenter = 32768
    ds.WindowWidth = 65536
    ds.PixelData = pixels.tobytes()
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(path, enforce_file_format=True)
    print(f"Created synthetic {'MONOCHROME1' if monochrome1 else 'MONOCHROME2'} DICOM: {path}")
    print("Contains synthetic pixels and synthetic identifiers only; not clinical data.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="sample-data/synthetic_cr.dcm")
    parser.add_argument("--monochrome1", action="store_true")
    parser.add_argument("--output-mono1", default="sample-data/synthetic_cr_mono1.dcm")
    args = parser.parse_args()
    create_dicom(Path(args.output), args.monochrome1)
    if not args.monochrome1:
        create_dicom(Path(args.output_mono1), True)


if __name__ == "__main__":
    main()
