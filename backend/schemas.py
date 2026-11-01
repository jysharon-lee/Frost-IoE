from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class ComplianceStatus(str, Enum):
    NORMAL = "NORMAL"        
    WARNING = "WARNING"      
    CRITICAL = "CRITICAL"    

class LiveZoneReading(BaseModel):
    zone_id: str = Field(..., description="Zone identifier, e.g. 'zone_a'")
    name: str = Field(..., description="Human-readable zone name")
    temp_c: Optional[float] = Field(None, description="Latest temperature in Celsius")
    humidity: Optional[float] = Field(None, description="Latest relative humidity percentage")
    power_ok: bool = Field(True, description="True if Mains, False if Battery Backup")
    source: str = Field("LIVE", description="'LIVE' or 'BACKFILL'")
    status: ComplianceStatus = Field(ComplianceStatus.NORMAL, description="Regulatory status")
    timestamp: datetime = Field(..., description="UTC timestamp of the reading")

class LiveZonesResponse(BaseModel):
    zones: List[LiveZoneReading]
    count: int
    server_time: datetime

class TrendPoint(BaseModel):
    timestamp: datetime
    temp_c: Optional[float] = None
    humidity: Optional[float] = None

class ZoneTrendResponse(BaseModel):
    zone_id: str
    hours: int
    point_count: int
    data: List[TrendPoint]