export default function Placeholder({ title }: { title?: string }) {
  return (
    <div className="bg-[#333333] flex items-center justify-center">
      <p className="text-white">{title}</p>
    </div>
  );
}