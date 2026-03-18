# Multi-Task Pipeline

## Overview

Learn how to compose multi-stage GPU compute pipelines.

## Pipeline Structure

```
Data → Preprocess → Model Inference → Postprocess → Output
```

## Basic Pipeline

```python
from deepiri_zepgpu.api.pipelines import PipelineBuilder
from deepiri_zepgpu.core.pipeline_manager import PipelineManager

# Define stage functions
def preprocess(data):
    # Normalize and augment data
    return (data - np.mean(data)) / np.std(data)

def inference(prepared_data):
    # Run model inference
    return model(prepared_data)

def postprocess(predictions):
    # Format output
    return {"predictions": predictions.tolist()}

# Build pipeline
stages = (
    PipelineBuilder("inference_pipeline")
    .add_stage(name="prep", func=preprocess)
    .add_stage(name="infer", func=inference, depends_on=["prep"], gpu_memory_mb=4096)
    .add_stage(name="format", func=postprocess, depends_on=["infer"])
    .build()
)

# Execute
manager = PipelineManager(scheduler)
pipeline_id = await manager.create_pipeline("my_pipeline", stages)
await manager.run_pipeline(pipeline_id)
```

## Pipeline with Data Flow

```python
def load_data(path):
    return np.load(path)

def extract_features(raw):
    # Process raw data
    return features

def train_model(features, labels, lr=0.01):
    # Training logic
    return trained_model

def evaluate(model, test_features, test_labels):
    # Evaluation
    return {"accuracy": 0.95}

stages = (
    PipelineBuilder("ml_training_pipeline")
    .add_stage(name="load", func=load_data)
    .add_stage(name="features", func=extract_features, depends_on=["load"])
    .add_stage(
        name="train",
        func=train_model,
        depends_on=["features"],
        args={"lr": 0.001},
    )
    .add_stage(name="eval", func=evaluate, depends_on=["train", "features"])
    .build()
)
```

## Parallel Stages

```python
def model_v1(data):
    return model1(data)

def model_v2(data):
    return model2(data)

def ensemble(pred1, pred2):
    return (pred1 + pred2) / 2

stages = (
    PipelineBuilder("ensemble_pipeline")
    .add_stage(name="preprocess", func=preprocess)
    .add_stage(name="model1", func=model_v1, depends_on=["preprocess"])
    .add_stage(name="model2", func=model_v2, depends_on=["preprocess"])
    .add_stage(
        name="ensemble",
        func=ensemble,
        depends_on=["model1", "model2"],
    )
    .build()
)
```

## Monitoring Pipeline

```python
status = manager.get_pipeline_status(pipeline_id)
print(f"Status: {status['status']}")
print(f"Completed: {status['completed_stages']}/{status['total_stages']}")
for name, stage_status in status["stages"].items():
    print(f"  {name}: {stage_status}")
```

## Error Handling

```python
def safe_inference(data):
    try:
        return model(data)
    except Exception as e:
        return {"error": str(e)}

stages = (
    PipelineBuilder("safe_pipeline")
    .add_stage(name="prep", func=preprocess)
    .add_stage(
        name="infer",
        func=safe_inference,
        depends_on=["prep"],
        max_retries=3,
    )
    .build()
)
```
