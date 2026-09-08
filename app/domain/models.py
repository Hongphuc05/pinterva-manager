from enum import EnumMeta, StrEnum


class LegacyOrderStateMeta(EnumMeta):
    def __getattr__(cls, name: str):
        val_upper = name.upper()
        if val_upper in {
            "DISCOVERED",
            "CLAIMED_IMPORTED",
            "OPEN_FOR_ALLOCATION",
            "ASSIGNMENT_PENDING_APPROVAL",
            "REASSIGNMENT_REQUIRED",
        }:
            return cls.OPEN
        if val_upper in {"ASSIGNED", "IN_PROGRESS"}:
            return cls.IN_PROGRESS
        if val_upper in {"RESULT_SUBMITTED", "QC_PENDING", "SUBMITTING_TO_SITE"}:
            return cls.QC_PENDING
        if val_upper in {"REVISION_REQUESTED", "REVISION"}:
            return cls.REVISION
        if val_upper in {"DONE", "SKIPPED"}:
            return cls.DONE
        if val_upper == "CANCELLED":
            return cls.CANCELLED
        if val_upper == "EXCEPTION":
            return cls.EXCEPTION
        return super().__getattr__(name)


class OrderState(StrEnum, metaclass=LegacyOrderStateMeta):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    QC_PENDING = "QC_PENDING"
    REVISION = "REVISION"
    DONE = "DONE"
    CANCELLED = "CANCELLED"
    EXCEPTION = "EXCEPTION"

    @classmethod
    def _missing_(cls, value: object) -> "OrderState":
        if isinstance(value, str):
            val_upper = value.upper()
            if val_upper in {
                "DISCOVERED",
                "CLAIMED_IMPORTED",
                "OPEN_FOR_ALLOCATION",
                "ASSIGNMENT_PENDING_APPROVAL",
                "REASSIGNMENT_REQUIRED",
            }:
                return cls.OPEN
            if val_upper in {"ASSIGNED", "IN_PROGRESS"}:
                return cls.IN_PROGRESS
            if val_upper in {"RESULT_SUBMITTED", "QC_PENDING", "SUBMITTING_TO_SITE"}:
                return cls.QC_PENDING
            if val_upper in {"REVISION_REQUESTED", "REVISION"}:
                return cls.REVISION
            if val_upper in {"DONE", "SKIPPED"}:
                return cls.DONE
            if val_upper == "CANCELLED":
                return cls.CANCELLED
            if val_upper == "EXCEPTION":
                return cls.EXCEPTION
        return super()._missing_(value)
