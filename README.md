# MangaTraductor (OCR y Traductor de Manga)

## Descripción General
Una potente herramienta para extraer texto en japonés de imágenes de manga, traducirlo al inglés usando la API de DeepL y reemplazar sin problemas el texto original con la traducción en inglés. Cuenta tanto con una Interfaz Gráfica de Usuario (GUI) interactiva muy completa, como con una Interfaz de Línea de Comandos (CLI) para procesamiento por lotes.

## Características
- **Aplicación GUI (`manga_translator_app.py`)**:
  - **Recorte Interactivo**: Selecciona regiones de texto directamente en la imagen con el ratón.
  - **OCR en Tiempo Real**: Utiliza el modelo VisionEncoderDecoder de Hugging Face para un reconocimiento de texto japonés rápido y preciso.
  - **Traducción con DeepL**: Se integra con la API de DeepL para traducir el texto japonés reconocido.
  - **Reemplazo de Texto**: Pinta automáticamente sobre el texto japonés original en blanco y dibuja la traducción adaptándola dinámicamente a la caja delimitadora.
  - **Navegación y Vista de Imágenes**: Soporta zoom, desplazamiento suave (`W`/`S`) y navegación rápida entre imágenes en una carpeta (`A`/`D`).
  - **Deshacer**: Incluye la función de deshacer para los reemplazos de texto.
- **Herramienta por Lotes CLI (`run_ocr.py`)**:
  - Procesa automáticamente múltiples imágenes colocadas en un directorio `images`.
  - Muestra el texto japonés extraído y su traducción en la consola.

## Requisitos Previos
Este proyecto requiere Python. Instala las dependencias necesarias usando `pip`:

```bash
pip install torch transformers Pillow requests
```
*(Nota: `tkinter` se usa para la interfaz gráfica y normalmente viene incluido con Python por defecto).*

## Configuración

1. **Modelo de OCR**: La funcionalidad de OCR utiliza el modelo `kha-white/manga-ocr-base` de Hugging Face. La librería `transformers` descargará el modelo automáticamente la primera vez que ejecutes la aplicación (requiere conexión a internet inicial). No necesitas descargar ningún archivo de modelo manualmente.
   
2. **Archivos de Fuentes**: La aplicación utiliza `font/animeace2_reg.ttf` para dibujar el texto traducido. Asegúrate de que la fuente esté ubicada en la carpeta `font/`. Si falta, recurrirá a una fuente del sistema por defecto.

3. **Clave API de DeepL**: 
   Necesitas una Clave API de DeepL para la traducción. Puedes obtener una clave de nivel gratuito en el [sitio web de DeepL API](https://www.deepl.com/pro-api).
   - La aplicación almacena esto de forma segura en `user_config.json`.
   - Puedes configurarlo fácilmente de forma directa desde la GUI haciendo clic en **API Key Settings**.

## Uso

### 1. Aplicación GUI (Modo Interactivo)
Inicia la aplicación de escritorio interactiva:
```bash
python manga_translator_app.py
```
- Haz clic en **Open Image** para cargar una página de manga.
- **Haz clic y arrastra** para dibujar un cuadro alrededor de la burbuja de texto en japonés que deseas traducir.
- Espera un momento; la salida del OCR y la traducción aparecerán en el panel derecho.
- Haz clic en **Replace Text in Image** para dibujar el texto traducido directamente sobre la imagen, cubriendo la burbuja original.
- Haz clic en **Save Image** para guardar tu imagen traducida.

### 2. Procesamiento por Lotes CLI (Modo Terminal)
Para procesar un lote de imágenes rápidamente a través de la consola:
```bash
python run_ocr.py
```
- Primero, coloca las imágenes que deseas procesar dentro de un directorio `images/` en la carpeta raíz.
- Ejecuta el script y este iterará a través de todas las imágenes, realizando el OCR y la traducción, e imprimiendo los resultados directamente en la terminal.