export default function Placeholder({ title }: { title?: string }) {
  return (
    <div className="bg-gray-300 dark:bg-neutral-700 flex items-center justify-center">
      <p className="text-black dark:text-white">{title}</p>
    {/* <div className="bg-[#333333] flex items-center justify-center">
      <p className="text-white">{title}</p> */}
    </div>
  );
}