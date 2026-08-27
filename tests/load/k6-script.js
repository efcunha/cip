// k6 script para teste de carga do CIP (Round 22+ Phase 2).
//
// Como rodar:
//   # 1. Subir infra
//   docker compose up -d
//   # 2. Instalar k6 (https://k6.io/docs/getting-started/installation)
//   # 3. Rodar
//   k6 run tests/load/k6-script.js
//   # 4. Com mais users
//   k6 run --vus 200 --duration 60s tests/load/k6-script.js
//
// Targets (200 concurrent users):
//   - p95 chat_message < 5s
//   - p99 chat_message < 15s
//   - error rate < 1%
//   - http_req_duration avg < 3s

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const TENANT = __ENV.TENANT || 'loadtest';

const chatErrors = new Counter('chat_errors');
const chatRate = new Rate('chat_success');
const chatDuration = new Trend('chat_duration_ms');

export const options = {
  stages: [
    { duration: '10s', target: 50 },   // ramp-up para 50
    { duration: '20s', target: 200 },  // ramp-up para 200
    { duration: '30s', target: 200 },  // steady 200
    { duration: '10s', target: 0 },    // ramp-down
  ],
  thresholds: {
    'http_req_duration{expected_response:true}': ['p(95)<5000', 'p(99)<15000'],
    'chat_success': ['rate>0.99'],
    'chat_errors': ['count<10'],
  },
};

const QUESTIONS = [
  'Quais sao os 6 pilares do AWS Well-Architected Framework?',
  'Como identificar desperdicio de custo em EC2 ocioso?',
  'Compare AWS Lambda vs Azure Functions.',
  'Quais as melhores praticas de seguranca em pods Kubernetes?',
];

function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

export function setup() {
  // Cria 1 conversa por VU (warmup)
  const res = http.post(`${BASE_URL}/chat/conversations`,
    JSON.stringify({ title: `k6-load-${Date.now()}` }),
    { headers: { 'Content-Type': 'application/json', 'X-Tenant-Id': TENANT } }
  );
  if (res.status === 201) {
    return { convId: JSON.parse(res.body).id };
  }
  return { convId: null };
}

export default function (data) {
  if (!data.convId) {
    sleep(5);
    return;
  }

  const question = pick(QUESTIONS);
  const start = Date.now();
  const res = http.post(
    `${BASE_URL}/chat/conversations/${data.convId}/messages`,
    JSON.stringify({
      question,
      cloud: pick(['aws', 'gcp', 'azure']),
    }),
    {
      headers: { 'Content-Type': 'application/json', 'X-Tenant-Id': TENANT },
    }
  );
  const duration = Date.now() - start;
  chatDuration.add(duration);

  const ok = check(res, {
    'status is 201': (r) => r.status === 201,
    'has answer': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.content && body.content.length > 0;
      } catch (e) {
        return false;
      }
    },
  });

  if (ok) {
    chatRate.add(1);
  } else {
    chatErrors.add(1);
    chatRate.add(0);
  }

  sleep(Math.random() * 3 + 1);  // 1-4s entre requests
}

export function handleSummary(data) {
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'tests/load/k6-summary.json': JSON.stringify(data, null, 2),
  };
}

import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.2/index.js';
