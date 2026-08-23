# SPEC-001 — Fare Engine

**Projeto:** UrbanoPay Mobilidade  
**Status:** Proposta para implementação

## 1. Objetivo

Implementar o motor tarifário determinístico responsável por validar trajetos, consultar tarifas vigentes, aplicar perfil tarifário, classificar viagem, aplicar desconto e retornar breakdown completo. O LLM nunca será a fonte oficial do cálculo.

## 2. Modais e tarifas iniciais

| Modal/Linha | Integral | Meia |
|---|---:|---:|
| BUS 101 | 6.00 | 3.00 |
| BUS 202 | 7.00 | 3.50 |
| BUS 303 | 8.00 | 4.00 |
| BUS 404 | 9.00 | 4.50 |
| BUS 505 | 10.00 | 5.00 |
| METRO | 10.00 | 5.00 |

Os valores devem existir como dados persistidos, nunca hard-coded na lógica.

## 3. Perfis
- `INTEGRAL`;
- `MEIA`.

Perfil inválido: `INVALID_FARE_PROFILE`.

## 4. Segmentos

Ônibus:
```json
{"mode":"BUS","line_code":"303"}
```

Metrô:
```json
{"mode":"METRO"}
```

## 5. Tipos de viagem

### SINGLE
Exatamente um segmento, ônibus ou metrô. Desconto 0%.

### COMMON
Dois ou mais segmentos exclusivamente de ônibus. Desconto 0%.

### INTEGRATION
Pelo menos um ônibus e um metrô. Desconto vigente inicial de 15%.

## 6. Ordem de cálculo
1. validar request;
2. validar segmentos;
3. validar perfil;
4. consultar tarifas vigentes;
5. aplicar tarifa do perfil em cada segmento;
6. calcular subtotal;
7. classificar viagem;
8. consultar regra vigente;
9. calcular desconto;
10. calcular total;
11. retornar breakdown.

A MEIA é aplicada por segmento antes do desconto de integração.

## 7. Dinheiro
- Python: `Decimal`;
- PostgreSQL: `NUMERIC/DECIMAL`;
- 2 casas decimais;
- `ROUND_HALF_UP`;
- contratos JSON usam string decimal.

## 8. Vigência
Tarifa e regra devem possuir `valid_from` e `valid_until`. Alterações futuras encerram a vigência anterior em vez de sobrescrever histórico.

## 9. Contrato de entrada
```json
{
  "fare_profile": "MEIA",
  "segments": [
    {"mode":"BUS","line_code":"303"},
    {"mode":"METRO"}
  ]
}
```

## 10. Contrato de saída
```json
{
  "fare_profile":"MEIA",
  "trip_type":"INTEGRATION",
  "segments":[
    {"mode":"BUS","line_code":"303","fare":"4.00"},
    {"mode":"METRO","fare":"5.00"}
  ],
  "subtotal":"9.00",
  "discount":{"type":"INTEGRATION","percentage":"15.00","amount":"1.35"},
  "total":"7.65",
  "currency":"BRL"
}
```

Preferencialmente retornar IDs internos das tarifas/regras aplicadas para auditoria.

## 11. Erros tipados
- `INVALID_FARE_PROFILE`;
- `INVALID_TRANSPORT_MODE`;
- `INVALID_SEGMENT_STRUCTURE`;
- `EMPTY_TRIP`;
- `BUS_LINE_REQUIRED`;
- `FARE_LINE_NOT_FOUND`;
- `FARE_NOT_AVAILABLE`;
- `FARE_RULE_NOT_FOUND`;
- `UNSUPPORTED_TRIP_COMPOSITION`;
- `FARE_SERVICE_UNAVAILABLE`.

Nenhum erro permite fallback do LLM para tarifa estimada.

## 12. Casos obrigatórios
- 101 integral = 6.00;
- 101 meia = 3.00;
- METRO integral = 10.00;
- METRO meia = 5.00;
- 101+303 integral COMMON = 14.00;
- 101+303 meia COMMON = 7.00;
- 303+METRO integral INTEGRATION = 15.30;
- 303+METRO meia INTEGRATION = 7.65;
- 505+METRO integral = 17.00;
- 505+METRO meia = 8.50;
- 101+303+METRO integral = 20.40;
- 101+303+METRO meia = 10.20;
- linha 999 => erro;
- perfil inválido => erro;
- trajeto vazio => erro;
- vigência antiga/nova => valor correspondente ao período.

## 13. Invariantes
- total >= 0;
- desconto <= subtotal;
- COMMON => desconto 0%;
- INTEGRATION => regra vigente;
- MEIA nunca utiliza tarifa integral;
- INTEGRAL nunca utiliza tarifa meia;
- mesma entrada + mesmas regras => mesmo resultado.

## 14. Arquitetura interna sugerida
- `FareService`;
- `FareRepository`;
- `FareRuleRepository`;
- `TripClassifier`;
- `FareCalculator`.

O Sales Agent acessa apenas tool estreita, por exemplo `calculate_trip_fare`.

## 15. Aceite
- todas as tarifas vêm do banco;
- classificação correta;
- 100% de acurácia nos casos determinísticos;
- Decimal/NUMERIC;
- histórico e vigência;
- breakdown completo;
- erros tipados;
- nenhum cálculo oficial no LLM.
