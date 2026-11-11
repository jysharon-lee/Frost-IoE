from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class ComplianceStatus(str, Enum):
    NORMAL = "NORMAL"        
    WARNING = "WARNING"      
    CRITICAL = "CRITICAL"    

class NodeReading(BaseModel):
    node_id: str = Field(..., description="Node identifier, e.g. 'node_1'")
    zone_id: str = Field(..., description="Parent zone identifier, e.g. 'zone_a'")
    name: str = Field(..., description="Human-readable node label, e.g. 'Corner 1 (node_1)'")
    temp_c: Optional[float] = Field(None, description="Latest node temperature in Celsius")
    humidity: Optional[float] = Field(None, description="Latest node relative humidity percentage")
    power_ok: bool = Field(True, description="True if Mains, False if Battery Backup")
    source: str = Field("LIVE", description="'LIVE' or 'BACKFILL'")
    status: ComplianceStatus = Field(ComplianceStatus.NORMAL, description="Regulatory status")
    timestamp: datetime = Field(..., description="UTC timestamp of the reading")

class LiveZoneReading(BaseModel):
    zone_id: str = Field(..., description="Zone identifier, e.g. 'zone_a'")
    name: str = Field(..., description="Human-readable zone name")
    temp_c: Optional[float] = Field(None, description="Latest average temperature in Celsius across nodes")
    humidity: Optional[float] = Field(None, description="Latest average relative humidity percentage across nodes")
    power_ok: bool = Field(True, description="True if Mains, False if Battery Backup")
    source: str = Field("LIVE", description="'LIVE' or 'BACKFILL'")
    status: ComplianceStatus = Field(ComplianceStatus.NORMAL, description="Regulatory status")
    timestamp: datetime = Field(..., description="UTC timestamp of the reading")
    nodes: List[NodeReading] = Field(default_factory=list, description="Individual sensor node readings in this zone")

class LiveZonesResponse(BaseModel):
    zones: List[LiveZoneReading]
    count: int
    server_time: datetime

class ZoneNodesResponse(BaseModel):
    zone_id: str
    nodes: List[NodeReading]
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

class NodeTrendResponse(BaseModel):
    zone_id: str
    node_id: str
    hours: int
    point_count: int
    data: List[TrendPoint]
