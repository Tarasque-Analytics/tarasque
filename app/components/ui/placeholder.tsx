export default function Placeholder({ title }: { title?: string }) {
  return (
    <div className="bg-gray-300 flex items-center justify-center">
      <p className="text-black">{title}</p>
    </div>
  );
}