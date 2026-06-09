import { useParams, useLoaderData } from "react-router";
export default function Model() {
  const { symbol } = useParams<{ symbol: string }>();

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="w-full max-w-md">{symbol} SHAP goes here</div>
    </div>
  );
}
