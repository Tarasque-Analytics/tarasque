export default function Placeholder({ title }: { title?: string }) {
  return (
    <div className="bg-gray-300 flex items-center justify-center">
      <p className="text-black">{title}</p>
    {/* <div className="bg-[#333333] flex items-center justify-center">
      <p className="text-white">{title}</p> */}
    </div>
  );
}