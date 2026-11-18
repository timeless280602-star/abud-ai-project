import React, { useEffect, useRef, useState } from "react";

export default function ChatImages({ images }) {
  const [preview, setPreview] = useState(null);
  const dialog = useRef(null), trigger = useRef(null);
  useEffect(() => {
    if (preview) dialog.current?.showModal();
  }, [preview]);
  function close() { dialog.current?.close(); setPreview(null); trigger.current?.focus(); }
  return <>
    <div className="chat-images">{images.map((image, index) => <figure key={image.id}>
      <button type="button" aria-label={`Preview generated image ${index + 1}`} onClick={(event) => { trigger.current = event.currentTarget; setPreview(image); }}>
        <img src={image.url} alt={`Generated image ${index + 1}`} loading="lazy" />
      </button>
      <figcaption><a href={`${image.url}?download=true`} download>Download image {index + 1}</a></figcaption>
    </figure>)}</div>
    {preview && <dialog ref={dialog} className="chat-image-preview" aria-label="Image preview" onCancel={(event) => { event.preventDefault(); close(); }}>
      <button type="button" onClick={close} autoFocus>Close preview</button>
      <img src={preview.url} alt="Generated image preview" />
      <a href={`${preview.url}?download=true`} download>Download image</a>
    </dialog>}
  </>;
}
