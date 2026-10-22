
window.MULETRACE_DATA = {
  accounts: {
    A001: {
      name: "Somchai J.",
      status: "normal",
      openedDays: 980,
      avgAmount: 3200
    },
    A024: {
      name: "Narin K.",
      status: "normal",
      openedDays: 510,
      avgAmount: 4100
    },
    B782: {
      name: "Woraporn S.",
      status: "watch",
      openedDays: 12,
      avgAmount: 2800
    },
    C991: {
      name: "Kittisak P.",
      status: "flagged",
      openedDays: 48,
      avgAmount: 5500
    },
    D201: {
      name: "Nattaya L.",
      status: "watch",
      openedDays: 75,
      avgAmount: 6000
    },
    F002: {
      name: "Anon T.",
      status: "flagged",
      openedDays: 20,
      avgAmount: 2500
    },
    X311: {
      name: "External synthetic",
      status: "external",
      openedDays: 9999,
      avgAmount: 3000
    },
    Y904: {
      name: "External synthetic",
      status: "external",
      openedDays: 9999,
      avgAmount: 3000
    },
    Z120: {
      name: "External synthetic",
      status: "external",
      openedDays: 9999,
      avgAmount: 3000
    }
  },

  transactions: [
    {id:"T001",from:"A001",to:"B782",amount:180000,time:"2026-09-16T02:13:00"},
    {id:"T002",from:"A024",to:"B782",amount:95000,time:"2026-09-16T02:14:00"},
    {id:"T003",from:"A001",to:"B782",amount:15000,time:"2026-09-15T22:08:00"},
    {id:"T004",from:"X311",to:"B782",amount:12000,time:"2026-09-16T01:45:00"},
    {id:"T005",from:"Y904",to:"B782",amount:8700,time:"2026-09-16T01:52:00"},
    {id:"T006",from:"B782",to:"C991",amount:90000,time:"2026-09-16T03:01:00"},
    {id:"T007",from:"B782",to:"D201",amount:70000,time:"2026-09-16T03:18:00"},
    {id:"T008",from:"C991",to:"F002",amount:82000,time:"2026-09-16T03:40:00"},
    {id:"T009",from:"D201",to:"F002",amount:52000,time:"2026-09-16T04:05:00"},
    {id:"T010",from:"Z120",to:"C991",amount:21000,time:"2026-09-14T09:11:00"}
  ],

  cases: [
    {
      caseId: "MT-1042",
      source: "A001",
      target: "B782",
      amount: 180000,
      time: "2026-09-16T02:13:00",
      status: "new",
      transactionId: "T001"
    },
    {
      caseId: "MT-1043",
      source: "A024",
      target: "B782",
      amount: 95000,
      time: "2026-09-16T02:14:00",
      status: "new",
      transactionId: "T002"
    }
  ],

  previousCases: [
    {
      caseId: "MT-0931",
      accounts: ["C991", "F002"],
      summary: "Rapid movement through C991 to F002; escalated for human review."
    },
    {
      caseId: "MT-0877",
      accounts: ["D201"],
      summary: "D201 received multiple inbound transfers in a short window."
    }
  ]
};