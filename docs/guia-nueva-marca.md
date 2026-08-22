# Guía para levantar una marca nueva en este pipeline

Este documento es para quien llega al proyecto y tiene que poner una marca
nueva a correr: qué configurar, en qué orden ejecutar las corridas, cuánto
cuesta cada fuente y qué errores ya cometimos con Avianca y LATAM para no
repetirlos. No es una referencia de flags de `main.py` (para eso está
`README.md` y el `--help` de cada comando) — es la secuencia de decisiones y
verificaciones que hay que tomar *antes* de confiar en cualquier número que
el dashboard termine mostrando.

**Alcance de esta guía:** cubre levantar una marca nueva de **aerolínea, en
Colombia**, sobre el código tal como existe hoy — que es exactamente lo que
demuestran Avianca y LATAM corriendo juntas con `--brand`. Si la marca nueva
es de otro país o de otro sector (restaurantes, retail, lo que sea), varias
constantes que hoy son globales en `config.py` (`LOCATION_CODE`,
`RECOGNIZED_MEDIA_DOMAINS`, el vocabulario de contexto aeronáutico, los
drivers de queja) tendrían que volverse parámetros por cliente antes de
empezar. Ese trabajo ya está diseñado — no implementado — en
`docs/superpowers/specs/2026-08-22-framework-multicliente-design.md`; léelo
primero si la marca nueva no es una aerolínea colombiana.

---

## 1. `config.BRANDS`: verifica cada handle contra la API antes de confiar en él

`config.BRANDS["NombreDeLaMarca"]` es el único lugar donde vive la
identidad de una marca: `name`, `keyword`, `instagram_profiles`, `domains`,
`review_domain`, `tiktok_hashtags`, `tiktok_official_accounts`,
`loyalty_program`, `color`, `logo` y `competitors`. Escribir ese diccionario
es el trabajo de cinco minutos. Lo que cuesta tiempo — y lo que ya nos costó
tiempo dos veces — es dar por buenos los valores sin verificarlos.

**El defecto ya nos pasó con LATAM y de nuevo con Avianca.** Cuando se
levantó LATAM la primera vez, `instagram_profiles` apuntaba a `latam_airlines`
y `latamcolombia`. Ninguno de los dos existe. El actor de Apify no lanza una
excepción cuando le pides un perfil que no existe: devuelve
`{"error": "not_found"}` por cada ítem, `apify_instagram.scrape()` descarta
esos ítems en silencio, y la corrida termina "exitosa" con **cero menciones
de Instagram** — sin ningún error visible en ningún log. El síntoma no es un
traceback, es un número sospechosamente bajo (o en cero) que nadie nota si
no lo está buscando a propósito. Los handles reales resultaron ser
`latamairlines` (cuenta global, 3,2M seguidores) y `latamairlines_colombia`
(cuenta local, verificada). El mismo patrón de fallo apareció otra vez, sin
que nadie lo hubiera puesto ahí a propósito: `aviancacolombia`, el segundo
perfil de Instagram que se asumía activo para Avianca, **tampoco existe**
(Instagram lo devuelve como `not_found`, verificado contra la API real) —
Avianca corre hoy con una sola cuenta oficial de Instagram, no dos, y el
dashboard lo declara explícitamente en el bloque de calidad de datos para
que nadie confunda "una cuenta menos" con "un hueco de captura".

La lección no es "revisa los handles a mano mirando el perfil en el
navegador" — eso ya se hizo y ya falló dos veces. La lección es: **antes de
correr un backfill real, haz una llamada de diagnóstico barata (unos
centavos, Fase 1 de Apify con `resultsLimit` chico) contra cada handle que
vayas a configurar, y confirma en la respuesta cruda que no viene
`error: not_found`.** Lo mismo aplica a `tiktok_official_accounts`: cada
cuenta que se declare "oficial" ahí debería venir de un ítem real de Apify
con `verified: true` y un conteo de seguidores que tenga sentido — no de
adivinar el handle a partir del nombre de la marca. Si el proyecto ya tiene
un test de regresión para esto (`tests/test_config.py` fija los handles
reales de LATAM con un test dedicado, exactamente para que un cambio
accidental no vuelva a romperlos en silencio), escribe uno análogo para la
marca nueva apenas verifiques sus handles — es la forma de que la próxima
persona no tenga que redescubrir el mismo bug.

`review_domain` merece la misma verificación: no asumas que el dominio raíz
de la marca es el que Trustpilot indexa. Se confirmó contra la API real que
`avianca.com` tiene 1.884 reseñas (1,2★ promedio) y `latamairlines.com` tiene
48 (1,6★) — una llamada de `business_data/trustpilot/reviews` con `depth`
chico basta para confirmar que el dominio existe en Trustpilot antes de
configurarlo como si existiera.

## 2. No uses hashtags genéricos para TikTok

`tiktok_hashtags` es la lista de hashtags que se buscan en TikTok para
encontrar contenido sobre la marca — y es la fuente de ruido más traicionera
del pipeline, porque el ruido *parece* contenido válido hasta que alguien lee
los textos uno por uno.

El caso medido: `#latam` trajo 29 videos, de los cuales **28 no tenían nada
que ver con la aerolínea** — memes de "países más ricos de Latinoamérica",
nieve, acentos regionales, terremotos, geografía. Un solo video (una reseña
de vuelo en portugués) era real. `#latamcolombia` no fue mucho mejor: de 35
videos, ~15 eran reales (~43%) y el resto era el mismo tipo de contenido
genérico sobre Colombia, no sobre la aerolínea — el video más visible del
lote, con 224.700 de alcance, era una fan de un grupo de K-pop quejándose de
que la banda nunca hace gira en Brasil o México, clasificado como "queja" y
sentado en el top de alcance del dashboard hasta que se corrigió. En
contraste, `#latamairlines` — el hashtag más específico, el que nadie usaría
para hablar de otra cosa — no tuvo ni un solo descarte: 18 de 18 videos eran
reales.

El patrón se repite siempre que el nombre de la marca coincide con una
palabra de uso general: "LATAM" es también la abreviatura de Latinoamérica,
y esa misma ambigüedad reapareció, sin que nadie la buscara, en el índice de
búsquedas de IA (`search_mentions`) — preguntas sobre "Aruba", "Miami" o
"Copacabana" citaban `latamairlines.com` como una fuente de viaje más, no
porque alguien le preguntara a un modelo por la aerolínea. **Antes de
declarar un hashtag en `tiktok_hashtags`, pide una muestra chica (20-30
resultados) y léela — no asumas que "la marca aparece en el texto" significa
"el texto habla de la marca".** Si el hashtag es una palabra o sigla que
también significa otra cosa en el idioma o la región del mercado, probablemente
va a traer ruido, y la decisión correcta —como se hizo con `#latam`— es
dejarlo fuera del todo, no intentar filtrarlo después a fuerza de reglas.
`pipeline/relevance.py` ya aplica un filtro de contexto aeronáutico sobre lo
que SÍ entra por hashtag, pero ese filtro reduce el ruido, no lo elimina —
un hashtag que aporta 3% de señal real sigue sin ser un hashtag que valga la
pena pagar.

## 3. El orden de las corridas

El orden importa porque varias etapas dependen de que la anterior ya haya
guardado datos, y porque algunas etapas cuestan dinero real y otras no —
correrlas en el orden equivocado significa pagar por algo que se puede
inferir gratis de lo que ya está en la base, o reintentar un scraping caro
porque la clasificación falló antes de que se guardara nada.

**Primero, el backfill histórico** (`--backfill --since <fecha>`, o
`--seed-excel` si hay datos de un pipeline anterior que migrar). Esta es la
corrida que paga Instagram y TikTok en vivo. `run_pipeline()` clasifica
automáticamente al final de la corrida — no hace falta un paso aparte para
eso salvo que algo haya fallado o que, como con este cambio, se necesite
reclasificar TODO lo ya guardado porque el clasificador ganó un campo nuevo.
Antes de correr el backfill completo, vale la pena correr una **sonda
barata de Fase 1** (posts, sin comentarios) para saber cuántos posts hay de
verdad — `INSTAGRAM_POSTS_LIMIT` es un tope duro, y si la marca publica
mucho, ese tope trunca la ventana de cobertura antes de llegar a
`REPORT_WINDOW_START` (le pasó a Avianca con el tope viejo de 80: la
cobertura no llegaba más atrás de 3 meses). Ver la sección 5 sobre por qué
la *profundidad* del muestreo, no solo su presencia, cambia los números que
el dashboard termina mostrando.

**Después, el enriquecimiento de engagement** (`--enriquecer-engagement`).
Este paso no gasta ni un centavo de API — relee el `raw` que cada scraper
ya guardó y de ahí extrae `saves`/`views`/`reach_source`, campos que el
pipeline anterior descartaba. Si se salta este paso, `engagement` termina
subestimando gravemente el alcance real (un video de TikTok con 61.500
reproducciones reportaba solo 2.216 de "engagement" en el esquema viejo,
porque solo sumaba likes+shares+comments). Correrlo es gratis y siempre
vale la pena correrlo apenas termine cualquier scraping nuevo.

**El backfill de alcance de Instagram** (`--enriquecer-instagram-reach`)
solo hace falta para menciones que se scrapearon con una versión del código
anterior a que el scraper trajera el alcance del post en la Fase 1 misma —
es decir, para deuda técnica de una marca vieja, no para una marca nueva.
Si la marca nueva se scrapea con el código actual, el alcance ya llega
poblado desde el primer scrape y este comando no aporta nada (fue
exactamente el caso de LATAM: 155 de 193 filas ya traían `reach_source`
='post' desde el scrape mismo). **Ojo con un detalle real del código:**
`pipeline/instagram_reach_backfill.py` no filtra por marca — si se corre
con dos marcas en la misma base, vuelve a pedir Fase 1 de los posts de
*todas* las marcas, no solo la que se quiere backfillear. No es un problema
si de verdad hace falta backfillear una marca nueva sola en la base, pero
si ya hay más de una marca, revisa el código antes de correrlo o vas a
pagar Apify por posts que no necesitabas tocar.

**Prensa y reseñas** (`--solo-prensa`, `--solo-resenas`) se corren aparte, a
propósito — no están en el `SCRAPERS` por defecto de una corrida semanal.
Cuestan centavos, pero cuestan, y una corrida rutinaria no debería gastarlos
sin que alguien lo pida. Ambas dependen únicamente de `brand["keyword"]` /
`brand["review_domain"]`, así que se pueden correr en cualquier momento
después de tener el perfil configurado — no dependen de que Instagram/TikTok
ya hayan corrido.

**Visibilidad en IA** (`--visibilidad-ia --brand X`, y una sola vez
`--comparar-marcas-ia` sin `--brand`) es la única etapa que no toca
`mentions` en absoluto — vive en tablas propias. Tiene sentido correrla al
final, después de que `competitors` esté bien declarado en el perfil de la
marca (la comparación directa y las plantillas de prompt con `{competitor}`
dependen de esa lista).

**Antes de dar por cerrada cualquier corrida**, corre la suite de tests
completa (debe seguir en verde) y reconcilia manualmente unos cuantos
invariantes contra la base real: cero menciones `unclassified` que deberían
estar clasificadas, cero quejas sin `complaint_driver`, cero fechas
"inventadas" (`date_confidence='exact'` con `published_at` NULL). Estos tres
chequeos aparecen, verificados en cero, en cada una de las corridas
anteriores documentadas en `.superpowers/` — es la forma más barata de
detectar que algo se rompió a mitad de una corrida larga.

## 4. Costos reales medidos, por fuente

Los números de abajo son gasto real verificado contra las APIs (no
estimaciones a priori) durante las corridas de Avianca y LATAM. Sirven como
referencia de orden de magnitud, no como cotización exacta — el costo real
de una marca nueva depende de cuánto publica y cuánta gente le comenta.

| Fuente | Tarifa verificada | Ejemplo real |
|---|---|---|
| Instagram (Apify, Fase 1 y Fase 2) | ~$0,0023 por resultado (post o comentario), constante entre fases | Backfill profundo de Avianca: 198 posts + ~6.030 comentarios ≈ $14,3. Muestra acotada de LATAM: 24 posts + 764 comentarios ≈ $1,55 |
| TikTok (Apify, búsqueda por hashtag) | Mismo mecanismo de cobro por resultado que Instagram | Los volúmenes típicos son mucho menores (decenas a un par de cientos de videos por marca) — en la práctica, bajo $1 por corrida |
| Prensa — Google News (DataForSEO) | ~$0,004 por marca por corrida (`depth=20`) | Verificado en desarrollo y en producción para Avianca y LATAM |
| Reseñas — Trustpilot (DataForSEO) | ~$0,00075 por marca por corrida (`task_post`; el `task_get` posterior es gratis, `depth=20`) | Igual, verificado dos veces |
| Visibilidad en IA — por marca (DataForSEO: métricas + fuentes + ejemplos + 6 prompts propios + share of voice) | ~$0,29 por marca | Avianca y LATAM, verificado |
| Visibilidad en IA — comparación directa (`multi_target_metrics`, una sola llamada, no por marca) | ~$0,10 | Una corrida cubre todas las marcas del cliente a la vez |
| Clasificación (DeepSeek, sentiment + driver + `is_service_conversation`) | No se mide en dólares por separado en ninguna corrida documentada — históricamente marginal frente a Apify en cada comparación de gasto | ~6.700 menciones (esta tarea) tardan del orden de 40 minutos en lotes de 100, reanudable si se corta |

**Lo que NO está en esta tabla:** el canal web (DataForSEO, `serp` general)
se probó, se midió y se retiró para Avianca/LATAM — 71 menciones entre las
dos marcas producían solo 2 quejas reales, y el resto era en su mayoría
agregadores de vuelos, spam SEO y contenido sin relación con el servicio
(un casino online, granjas de teléfonos falsos suplantando el call center).
No es una limitación técnica: es una decisión de producto para *estas dos*
marcas, tomada después de medir la señal real. Para una marca nueva —
sobre todo si su presencia en redes es más débil que la de una aerolínea
grande — vale la pena volver a evaluar esta fuente en vez de asumir que
también hay que descartarla.

Antes de comprometer presupuesto a un backfill grande, corre siempre una
sonda de Fase 1 barata y proyecta el gasto con la tarifa por resultado de
la tabla — el backfill de Avianca terminó gastando ~2x lo estimado porque
el ratio real de comentarios por post en los meses más antiguos resultó
mucho mayor que el histórico que se usó para proyectar.

## 5. Trampas de medición que ya nos costaron tiempo

Cinco maneras concretas en las que un número que "se ve razonable" resulta
estar midiendo otra cosa. Todas se descubrieron con datos reales de este
proyecto, no en abstracto.

**Profundidad de muestreo.** La tasa de queja de una cuenta no es estable
según cuántos comentarios por post se scrapeen — cambia de forma medible
según qué tan profundo se muestree, y el efecto puede ser grande. El caso
más extremo medido: la misma cuenta de LATAM, en la misma ventana de
fechas, pasó de 94,3% de tasa de queja (muestra superficial, mediana de 12
comentarios/post) a 43,8% (muestra profundizada, mediana de 36,5
comentarios/post) — y la mediana de tasa de queja *por post* cayó de 100%
a 36,4%. La causa: con pocos comentarios por post, lo primero que trae el
scraper tiende a sesgarse hacia lo más reciente o lo más señalado, que no
es necesariamente representativo. La instrucción práctica: **antes de
comparar dos marcas, o de reportar una tasa como definitiva, verifica que
la mediana de comentarios por post sea del mismo orden de magnitud entre
lo que estás comparando** — si una cuenta tiene 15 comentarios/post de
mediana y la otra 30, la comparación directa entre sus tasas de queja no es
honesta todavía.

**Colapso de voces repetidas.** Una persona real que pega el mismo texto
varias veces bajo distintos posts (o el mismo post) genera varias filas
crudas que son, en realidad, una sola voz insistiendo — no varias personas
independientes. Sin colapsar por (autor, texto), una porción sustancial de
las quejas resulta ser repetición: alrededor de un tercio del volumen de
quejas en el proyecto salió de este patrón (verificado también en una
medición fresca sobre LATAM: 41,3% de las filas crudas de queja se
colapsaron en voces únicas). El caso extremo documentado: una sola persona
(`alejandra.caicho`) generó 56 filas repartidas en apenas 4 textos casi
idénticos (48/6/1/1 repeticiones), cada fila con su propio `source_url` de
comentario real — el scraper no tenía ningún error, cada fila es un
comentario real y distinto, pero contarlas como 56 voces distorsiona
cualquier distribución de drivers que se calcule encima. `dashboard/
aggregate.py` colapsa por `(brand, author, text)` antes de calcular
cualquier bloque, y expone `repeat_count` para no esconder la insistencia,
solo para no contarla varias veces como si fueran personas distintas.

**Alcance heredado del post, no sumable entre comentarios.** Cuando un
comentario de Instagram no tiene alcance propio (Instagram no expone
reproducciones de un comentario individual), lo único disponible es la
visibilidad del *post* donde apareció — y esa visibilidad es la misma para
los quince comentarios que haya bajo ese post. Sumarla por cada comentario
(y peor, por cada repetición de una misma voz bajo el mismo post) multiplica
la misma audiencia una y otra vez sin que haya más gente viéndolo de verdad.
La regla que terminó aplicándose: el alcance heredado del post (`post_reach`)
nunca se suma con el alcance propio (`views`, que solo existe en TikTok hoy),
nunca se usa para ordenar quejas por impacto, y se deduplica por post antes
de sumar entre repeticiones de una misma voz — se muestra como contexto
("dónde apareció esto"), nunca como si fuera "cuánta gente vio esta queja".

**Cuentas globales mezcladas con locales.** Cuando una marca publica desde
más de una cuenta oficial (una internacional/continental y una local), un
promedio agregado esconde que el problema puede estar concentrado en una
sola de ellas. El caso medido: LATAM global (`@latamairlines`) mostró 78,7%
de tasa de queja (mediana por post: 92%) mientras que LATAM Colombia/local
mostró 19,8% (mediana: 17,9%) — prácticamente empatada con Avianca (21,5%).
El titular agregado de LATAM (una tasa intermedia, alrededor de 35-40%) no
es falso, pero esconde que una de las dos cuentas se comporta como una
aerolínea en crisis y la otra como una aerolínea normal. La regla: reportar
siempre el desglose por cuenta de origen junto al agregado, nunca el
agregado solo — es lo que hace visible la asimetría en vez de promediarla
hasta que desaparece.

**El denominador contaminado por campañas de marketing** (el hallazgo que
motivó el cambio de tasa de queja de este mismo commit). Cuando la marca
corre una campaña activa — un mundial de fútbol, una promoción, lo que
sea — una parte real y a veces grande del volumen de menciones es gente
reaccionando al contenido o a la campaña ("¡Genial este contenido!", "Modo
mundial activado"), no evaluando el servicio. Mezclar esas menciones en el
mismo denominador que las quejas de servicio hunde la tasa de queja
artificialmente — no porque el servicio haya mejorado, sino porque el
denominador se llenó de gente que nunca opinó de él. La solución no es
filtrar por sentiment (el ejemplo "la mejor aerolínea en mi opinión" es
positivo y sí es conversación de servicio) ni por presencia de emojis —
ambas hipótesis se probaron y no funcionaron. Lo que funciona es que el
clasificador etiquete explícitamente si el texto es conversación sobre el
servicio o reacción a contenido/campaña (ver `pipeline/classifier.py`,
campo `is_service_conversation`), y que el dashboard reporte las dos tasas
— sobre conversación de servicio (principal) y sobre el total (secundaria,
para no perder comparabilidad con lo ya reportado) — nunca una sola como si
fuera la única lectura posible.

## 6. Taxonomía de drivers: cuándo extenderla

`config.COMPLAINT_DRIVERS` es la lista fija de motivos operativos que el
clasificador puede asignar a una queja, con un orden de precedencia
explícito para los casos que encajan en más de uno a la vez (ver el
docstring de `build_system_prompt` en `pipeline/classifier.py` para el
razonamiento completo de por qué ese orden y no otro). El error a evitar no
es "elegir mal los drivers iniciales" — es **no volver a mirarlos una vez
que hay datos reales**.

El caso que ya vivimos: "otro" fue, durante un tiempo, el driver #1 de
Avianca — 202 quejas, 28,7% del total, una caja negra que no respondía nada.
La forma de resolverlo no fue adivinar categorías nuevas a priori: se pasó
el lote completo de quejas "otro" (de ambas marcas) por el clasificador en
tandas, pidiéndole que describiera y agrupara los temas sin categorías
predefinidas, con un codebook que se fue afinando entre tandas para
converger en nombres consistentes. El resultado, con volumen verificado, dio
tres drivers nuevos con causa real: `rechazo_marca` (67% del lote de
"otro" — rechazo o insulto genérico sin causa operativa, que merecía nombre
propio en vez de perderse en "otro"), `mascotas` (~28, pérdida o maltrato
de mascotas en el vuelo) y `fraude_publicidad` (~21, suplantación de la
marca o publicidad que el usuario considera engañosa). Igual de importante:
algunos temas que parecían candidatos a driver propio **no llegaron a tener
volumen real** y se quedaron dentro de "otro" a propósito — amenazas legales
(~7), fallas de app (~6), solicitudes de rutas nuevas o ayuda humanitaria
(~30, que además son peticiones, no quejas de servicio). Una hipótesis
explícita del cliente ("denegación de embarque") se buscó a mano en **todas**
las quejas, no solo en "otro", y no apareció con volumen propio — la
hipótesis no se sostuvo y no se inventó un driver para sostenerla.

La instrucción concreta para una marca nueva: no asumas que la lista de
drivers de Avianca sirve tal cual para otra marca, ni siquiera para otra
aerolínea — LATAM, corriendo con la misma lista, tuvo "otro" en apenas 7,6%
(nada que recalibrar) porque su distribución real de quejas es distinta
(equipaje domina con 44,9%). El proceso correcto es: correr la marca nueva
con la lista semilla, medir qué porcentaje cae en "otro" después de tener
volumen real, y solo si ese porcentaje es alto (como el 28,7% de Avianca, no
el 7,6% de LATAM) vale la pena el ejercicio de recalibración — con el mismo
método (codebook evolutivo contra datos reales, nunca categorías inventadas
sin volumen que las respalde).

## 7. Qué verificar antes de dar por buena una comparación entre marcas

Cada uno de los puntos de la sección 5 tiene una contraparte de
verificación específica. Antes de poner dos marcas lado a lado en cualquier
reporte o conclusión:

- **Profundidad comparable.** Confirma que la mediana de comentarios por
  post (o el equivalente en la plataforma que corresponda) sea del mismo
  orden entre las dos marcas. Si una tiene una ventana de cobertura mucho
  más profunda que la otra (más posts, más meses hacia atrás), acota la
  comparación a la intersección real de cobertura de ambas — no a lo que
  cada una alcanzó a scrapear por separado.
- **Mismo criterio de exclusión aplicado a las dos.** El filtro de
  relevancia de hashtag (TikTok) y el retiro de canal web, si aplica, deben
  estar corridos y reconciliados para ambas marcas antes de comparar — una
  marca con ruido sin filtrar y otra ya limpia no es una comparación justa.
- **Desglose por cuenta, no solo el agregado**, si alguna de las marcas
  publica desde más de una cuenta oficial (global + local, por ejemplo). El
  agregado solo puede esconder que el problema está concentrado en una sola
  cuenta.
- **Mismo denominador, declarado explícitamente.** Si se está comparando la
  tasa de queja, aclara si es sobre conversación de servicio o sobre el
  total de menciones — mezclar una marca reportada sobre un denominador y
  otra sobre el otro produce una comparación que parece homogénea y no lo
  es.
- **La taxonomía de drivers es comparable en significado**, aunque los
  porcentajes difieran legítimamente entre marcas (ver sección 6) — si una
  marca tiene un `"otro"` inflado sin recalibrar y la otra no, cualquier
  conclusión sobre "de qué se queja más la gente" en una marca frente a la
  otra es prematura hasta que ambas estén calibradas con el mismo rigor.
- **El prompt del clasificador nombra a la marca correcta.** Es un error
  fácil de cometer y difícil de notar a simple vista: verificar (hay un test
  end-to-end que lo hace para este proyecto) que el system prompt enviado a
  DeepSeek para la marca B no siga mencionando el nombre o el programa de
  fidelidad de la marca A.
- **Los números reconcilian cualitativamente, no se buscan idénticos.**
  Si alguien (un cliente, un stakeholder) ya hizo su propia medición manual
  con un criterio de profundidad distinto al del dashboard, espera una
  diferencia de unos pocos puntos, no una coincidencia exacta — la
  población completa nunca va a dar el mismo número que un muestreo
  filtrado a mano, y eso no es un error de ninguno de los dos.
