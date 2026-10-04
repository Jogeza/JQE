export interface AssistantImage { url: string; name: string }

export async function prepareAssistantImage(file: File): Promise<AssistantImage> {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('Choose a PNG, JPEG or WebP screenshot.');
  if (file.size > 8_000_000) throw new Error('Choose an image smaller than 8 MB.');
  const image = await createImageBitmap(file);
  try {
    if (!image.width || !image.height || image.width * image.height > 40_000_000) throw new Error('Image dimensions are too large.');
    const ratio = Math.min(1, 1600 / Math.max(image.width, image.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.width * ratio)); canvas.height = Math.max(1, Math.round(image.height * ratio));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Image preparation is unavailable in this browser.');
    context.fillStyle = '#ffffff'; context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const url = canvas.toDataURL('image/jpeg', .88);
    if (url.length > 2_600_000) throw new Error('Image is too large after resizing. Choose a smaller screenshot.');
    return { url, name: file.name };
  } finally { image.close(); }
}
