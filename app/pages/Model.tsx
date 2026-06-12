import { useParams } from "react-router";
import { useEffect, useState } from "react";
import { ModelDataProvider }  from "~/context/ModelDataContext"
import { loadModelData } from "~/utils/model";
import type { ModelDataPayload } from "~/utils/model";

export default function Model() {
  const { symbol } = useParams<{ symbol: string }>();
  const [data, setData] = useState<ModelDataPayload | null>(null);

  useEffect(() => {
    loadModelData(symbol).then(setData);
  }, [symbol]);


  return (

    <div className="flex min-h-[60vh] items-center justify-center">
      <ModelDataProvider data={data}>
        {/**Place components here */}
        <div className="w-full max-w-md">{symbol} SHAP goes here</div>
      </ModelDataProvider>
    </div>
  );
}
