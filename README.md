# Coleta de Dados Climáticos para Logística (INMET / ClimaTempo)

Empresas de logística e agronegócio dependem de dados climáticos em tempo real para tomada de decisões. A proposta é construir um robô que consolida previsões para múltiplas capitais/cidades.

## Fonte de dados

- INMET (Instituto Nacional de Meteorologia)
https://portal.inmet.gov.br/

## Desafio com Selenium

- Interagir com mapas interativos ou menus de previsão por municípios
- Lidar com tabelas dinâmicas de previsão do tempo

## Tratativa dos dados

- Raspar temperatura máxima, mínima e probabilidade de chuva para uma lista de cidades (lida de um arquivo `.txt` ou `.csv`)
- Criar um alerta visual (ou log) quando a probabilidade de chuva para uma região ultrapassar 80%, simulando um aviso de risco para frotas de transporte
