class DomainRules:
    """Input checks shared by the existing greenhouse record and command paths."""
    CLIMATE_SIGNALS={"air_temperature","humidity","co2"}
    @classmethod
    def validate_target(cls,name: str,value: float) -> float:
        if name not in cls.CLIMATE_SIGNALS: raise ValueError("unsupported climate target")
        value=float(value)
        if name=="humidity" and not 0<=value<=100: raise ValueError("humidity out of range")
        return value
    @staticmethod
    def normalize_zone(value: str) -> str:
        value=value.strip().lower()
        if not value: raise ValueError("zone is required")
        return value
