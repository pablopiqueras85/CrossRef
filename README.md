# CrossRef

Herramienta para encontrar la equivalencia exacta de un componente electrónico en nuestro catálogo web a partir de la información que se recibe de un proveedor, cliente o compañero.

## Problema

La información de un componente puede llegar en formatos poco uniformes: una referencia parcial, una descripción libre o una lista de valores técnicos como impedancia, atenuación, frecuencia, potencia y encapsulado. Buscar manualmente una pieza equivalente en el catálogo consume tiempo y puede provocar sustituciones incorrectas.

CrossRef convierte esos datos en una búsqueda estructurada y devuelve únicamente componentes del catálogo que cumplan la equivalencia definida.

## Objetivo

Permitir que una persona:

1. Introduzca un componente y sus valores técnicos.
2. Seleccione o confirme el tipo de componente y las unidades.
3. Consulte una equivalencia **1:1** en el catálogo web.
4. Vea qué valores coinciden, cuáles faltan y por qué una referencia ha sido aceptada o descartada.

La herramienta no debe proponer una sustitución aproximada sin indicarlo explícitamente. Una coincidencia 1:1 significa que todos los campos obligatorios del tipo de componente cumplen las reglas de equivalencia configuradas.

## Alcance del MVP

- Formulario para introducir una referencia, descripción y parámetros técnicos.
- Normalización de unidades, separadores decimales, mayúsculas y nombres habituales de campos.
- Catálogo interno sincronizado desde el catálogo web mediante API, exportación o conector.
- Búsqueda por tipo de componente y atributos normalizados.
- Resultado con estado `equivalente`, `no encontrado` o `requiere revisión`.
- Comparación lado a lado de los valores de entrada y los de la referencia encontrada.
- Registro de la fuente y de la fecha de actualización del dato del catálogo.

Quedan fuera del primer MVP las recomendaciones basadas en similitud, las sustituciones con tolerancias no aprobadas y la compra automática.

## Flujo previsto

```text
Entrada libre o formulario
	|
	v
Identificación del tipo de componente
	|
	v
Normalización de nombres, unidades y valores
	|
	v
Aplicación de reglas de equivalencia
	|
	v
Búsqueda en el catálogo
	|
	v
Comparación explicable y resultado 1:1
```

## Datos de entrada

Los campos dependen del tipo de componente. Como punto de partida, CrossRef debe poder trabajar con:

- Referencia o part number recibido.
- Fabricante, si se conoce.
- Tipo de componente.
- Descripción original.
- Impedancia.
- Atenuación.
- Frecuencia mínima y máxima.
- Potencia nominal.
- Tensión o corriente nominal.
- Tolerancia.
- Encapsulado, montaje y conectores.
- Cualquier valor adicional relevante para esa familia.

Los campos obligatorios y las reglas de comparación deben definirse por familia de producto. Por ejemplo, un valor numérico puede requerir igualdad exacta, mientras que un rango de frecuencia puede requerir que el componente del catálogo cubra todo el rango solicitado.

## Resultado esperado

Cada resultado debe incluir:

- Referencia del catálogo.
- Fabricante y descripción.
- Enlace a la ficha del catálogo web.
- Valores de entrada y valores del catálogo normalizados.
- Estado de cada atributo: `coincide`, `no coincide`, `no informado` o `no aplicable`.
- Regla aplicada y motivo del resultado.
- Fecha y fuente de la información.

Ejemplo de respuesta conceptual:

```json
{
  "status": "equivalente",
  "catalog_reference": "CAT-000123",
  "source_reference": "REF-EXTERNA-01",
  "matched_fields": ["impedancia", "atenuacion", "frecuencia"],
  "differences": [],
  "catalog_url": "https://catalogo.example/componentes/CAT-000123"
}
```

## Reglas de equivalencia

Las reglas deben ser explícitas, versionadas y revisables. Una posible configuración por atributo es:

| Tipo de dato | Regla inicial |
| --- | --- |
| Texto normalizado | Igualdad después de normalizar |
| Valor con unidad | Igualdad tras convertir a una unidad base |
| Rango | El rango del catálogo cubre el rango solicitado |
| Tolerancia | Cumple el límite definido para la familia |
| Lista de valores | Coincidencia exacta de los valores requeridos |
| Campo desconocido | No confirmar equivalencia; requiere revisión |

Cuando falte un dato obligatorio o exista una discrepancia, el sistema debe explicar el motivo en lugar de ocultarlo tras una puntuación.

## Arquitectura propuesta

```text
Interfaz de usuario
	|
API de CrossRef
   |         |
Normalizador  Motor de reglas
	|         |
	+--- Índice o base de datos del catálogo
			 |
		 Conector del catálogo web
```

La fuente del catálogo debe tratarse como una dependencia intercambiable. Se prioriza una API o exportación oficial; el scraping solo debe utilizarse si está permitido y si no existe una alternativa estable.

## Plan de desarrollo

### Fase 1: definición y datos

- Confirmar las familias de componentes prioritarias.
- Definir el esquema de atributos y las unidades canónicas.
- Obtener una muestra real del catálogo y de consultas recibidas.
- Documentar las reglas que determinan una equivalencia 1:1.

### Fase 2: MVP funcional

- Implementar el modelo de datos del catálogo.
- Construir la normalización de entradas.
- Implementar un primer motor de reglas determinista.
- Añadir la búsqueda y la comparación explicable.
- Probar con casos positivos, negativos y datos incompletos.

### Fase 3: operación

- Automatizar la sincronización del catálogo.
- Añadir historial de reglas y resultados.
- Medir búsquedas sin resultado y revisiones manuales.
- Incorporar nuevas familias de componentes sin modificar el núcleo.

## Criterios de aceptación del MVP

- Una entrada con unidades equivalentes produce el mismo resultado aunque cambie el formato recibido.
- Una discrepancia en un campo obligatorio impide marcar el componente como equivalente.
- Un componente con datos incompletos aparece como `requiere revisión` o `no encontrado`, nunca como coincidencia confirmada.
- Cada resultado muestra los campos comparados y la regla aplicada.
- La referencia resultante enlaza con la ficha correspondiente del catálogo.
- La sincronización conserva la fuente y la fecha de cada registro.

## Preguntas abiertas

- ¿Qué familias de componentes y atributos son prioritarios?
- ¿El catálogo web dispone de API, exportación periódica o solo interfaz web?
- ¿Qué campos son obligatorios para cada familia?
- ¿Qué tolerancias comerciales o técnicas están autorizadas?
- ¿Debe haber revisión y aprobación humana antes de confirmar una equivalencia?
- ¿Se necesita autenticación, multiusuario o trazabilidad por usuario?

## Estado

En definición. Este repositorio contiene actualmente la especificación inicial del producto.
