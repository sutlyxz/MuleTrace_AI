/*
  MuleTrace AI — Frontend Configuration

  apiUrl:
    สำหรับส่งคำขอ AI ไปยัง Backend

  casesApiUrl:
    สำหรับดึงรายการเคสจาก Backend

  ห้ามใส่ AWS Access Key หรือ Secret Key ในไฟล์นี้
*/

const _origin =
  typeof window !== "undefined" && window.location?.origin
    ? window.location.origin
    : "http://localhost:8000";

window.MULETRACE_CONFIG = {
  apiUrl: `${_origin}/api/ai/summary`,
  casesApiUrl: `${_origin}/api/cases`,
  agentApiUrl: `${_origin}/api/ai/investigate`
};