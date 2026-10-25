"""Training-time augmentations. These transforms are never applied at inference."""


def build_train_transform():
    try:
        import albumentations as A
        from albumentations.pytorch import ToTensorV2
    except ImportError as exc:
        raise RuntimeError("Install pinned albumentations 2.0.8 from requirements.txt") from exc

    # FLAG: albumentations 1.x uses different constructor names; requirements pins >=2 API.
    return A.Compose(
        [
            A.RandomResizedCrop(size=(512, 512), scale=(0.85, 1.0), p=0.5),
            A.CLAHE(clip_limit=(1.0, 4.0), tile_grid_size=(8, 8), p=0.4),
            A.RandomGamma(gamma_limit=(70, 150), p=0.35),
            A.RandomToneCurve(scale=0.15, p=0.25),
            A.RandomBrightnessContrast(brightness_limit=0.15, contrast_limit=0.15, p=0.3),
            A.OneOf(
                [
                    A.GaussianBlur(blur_limit=(3, 5)),
                    A.Sharpen(alpha=(0.1, 0.3), lightness=(0.8, 1.2)),
                    A.Downscale(scale_range=(0.5, 0.9), interpolation_pair={"downscale": 1, "upscale": 1}),
                ],
                p=0.25,
            ),
            A.GaussNoise(std_range=(0.01, 0.05), p=0.2),
            A.ImageCompression(quality_range=(60, 95), p=0.2),
            A.Affine(
                scale=(0.9, 1.1),
                translate_percent={"x": (-0.05, 0.05), "y": (-0.05, 0.05)},
                rotate=(-8, 8),
                p=0.4,
            ),
            A.ElasticTransform(alpha=300, sigma=20, p=0.1),
            A.CoarseDropout(
                num_holes_range=(1, 8),
                hole_height_range=(0.02, 0.08),
                hole_width_range=(0.02, 0.08),
                fill=0,
                p=0.15,
            ),
            A.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
            ToTensorV2(),
        ]
    )


# Intentionally no HorizontalFlip: radiograph laterality is clinically meaningful.
